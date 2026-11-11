"""Fitness function: ``requirements-lock.txt`` is what the image installs, so
it must pin every package with hashes and match ``requirements.txt`` both ways.

``requirements.txt`` names what the bot needs; the lock fixes every package,
transitive ones included, to one version and its hashes (ADR 0007). The lock
is generated, never edited. These tests catch ``requirements.txt`` edited
without regenerating it: a requirement added, removed or narrowed. Extras and
environment markers are refused outright, because a lock resolved for one
platform cannot show whether they were honoured; adding one means extending
this check first.
"""

import pytest
from packaging.requirements import Requirement

from tests.characterization.fake_tradelocker import TRADELOCKER_VERSION
from tests.dependency_lock import canonical, mismatches, read_lock, requirement_lines

LOCK = read_lock()
DIRECT = {canonical(Requirement(line).name): Requirement(line) for line in requirement_lines()}


def test_every_locked_package_carries_hashes():
    assert LOCK.pins, "the lock pins nothing - the path is wrong, not the rule"
    assert {name for name, count in LOCK.hashes.items() if count == 0} == set()


def test_the_lock_marks_exactly_the_direct_requirements_as_direct():
    # Both ways: a requirement removed from requirements.txt but still marked
    # direct means its whole tree ships from a stale lock.
    assert LOCK.direct == set(DIRECT)


def test_every_direct_requirement_is_satisfied_by_its_pin():
    unsatisfied = [
        str(req) for name, req in DIRECT.items()
        if not req.specifier.contains(LOCK.pins.get(name, "0+missing"), prereleases=True)
    ]
    assert unsatisfied == []


def test_direct_requirements_have_no_extras_or_markers():
    assert [str(req) for req in DIRECT.values() if req.extras or req.marker] == []


def test_the_lock_pins_the_characterized_client_version():
    assert LOCK.pins["tradelocker"] == TRADELOCKER_VERSION


LOCKED = {"fastapi": "1.0", "pyjwt": "2.0"}


@pytest.mark.parametrize(
    ("installed", "exact", "expected"),
    [
        ({"fastapi": "1.0", "pyjwt": "2.0", "pip": "25.0", "setuptools": "70.0", "wheel": "0.4"}, True, ([], [])),
        ({"fastapi": "1.0", "pyjwt": "2.0", "pytest": "9.0"}, False, ([], [])),
        ({"fastapi": "1.0", "pyjwt": "2.0", "colorama": "0.4"}, True, ([], ["colorama==0.4"])),
        ({"fastapi": "1.1", "pyjwt": "2.0"}, False, (["fastapi==1.0"], [])),
        ({"fastapi": "1.0"}, True, (["pyjwt==2.0"], [])),
    ],
)
def test_installed_packages_are_compared_with_the_lock(installed, exact, expected):
    assert mismatches(installed, LOCKED, exact) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("PyJWT", "pyjwt"),
        ("typing_extensions", "typing-extensions"),
        ("ruamel.yaml", "ruamel-yaml"),
        ("A__b-.C", "a-b-c"),
    ],
)
def test_names_compare_in_normalized_form(name, expected):
    assert canonical(name) == expected


def _write(tmp_path, text):
    path = tmp_path / "requirements-lock.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_parser_reads_pins_hashes_and_direct_marks(tmp_path):
    lock = read_lock(_write(tmp_path, (
        "# header\n"
        "Annotated_Doc==0.0.6 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n    # via fastapi\n"
        "fastapi==1.0 \\\n    --hash=sha256:cc\n    # via -r requirements.txt\n"
    )))

    assert lock.pins == {"annotated-doc": "0.0.6", "fastapi": "1.0"}
    assert lock.hashes == {"annotated-doc": 2, "fastapi": 1}
    assert lock.direct == {"fastapi"}


@pytest.mark.parametrize(
    "text",
    [
        "fastapi[standard]==1.0 \\\n    --hash=sha256:aa\n",
        "    --hash=sha256:aa\nfastapi==1.0\n",
        "fastapi @ https://x\n",
    ],
)
def test_the_parser_refuses_a_line_it_does_not_understand(tmp_path, text):
    with pytest.raises(ValueError, match="unexpected lock line"):
        read_lock(_write(tmp_path, text))
