"""Fitness function: the lock holds everything its packages need, and each
override in ``requirements-overrides.txt`` is both honoured and still needed.

The image installs the lock with ``--no-deps``, because the overrides
contradict the ``tradelocker`` client's exact pins and pip would refuse them
(ADR 0017). pip therefore no longer checks that each locked package's
requirements are locked too; ``python -m tests.dependency_closure`` does, in
CI, against the metadata of the installed lock. These tests pin the rules it
applies, and check the overrides against the lock itself.
"""

import pytest
from packaging.specifiers import SpecifierSet

from tests.dependency_closure import override_problems, read_overrides, stale_overrides, unmet
from tests.dependency_lock import read_lock

LOCK = read_lock()
OVERRIDES = read_overrides()


def test_the_lock_holds_every_override_at_a_version_it_allows():
    assert OVERRIDES, "no overrides read - the path is wrong, not the rule"
    assert override_problems(LOCK.pins, OVERRIDES) == []


PINS = {"app": "1.0", "lib": "2.0", "jwt": "2.15.1"}


@pytest.mark.parametrize(
    ("requires", "expected"),
    [
        ({"app": ["lib>=2"]}, []),
        ({"app": ["Lib (>=1,<3)"]}, []),
        ({"app": ["lib>=3"]}, ["app needs lib>=3, the lock holds lib==2.0"]),
        ({"app": ["missing"]}, ["app needs missing, which the lock does not hold"]),
        # Markers are read for the image's platform, not the one running the
        # check: Windows-only and pre-3.11 requirements do not apply.
        ({"app": ['colorama; sys_platform == "win32"']}, []),
        ({"app": ['tomli; python_version < "3.11"']}, []),
        ({"app": ["missing; python_version >= '3.11'"]},
         ["app needs missing; python_version >= '3.11', which the lock does not hold"]),
        ({"app": ['crypto; extra == "crypto"']}, []),
        # An extra pulls in requirements this check does not follow.
        ({"app": ["lib[fast]>=2"]}, ["app needs lib[fast]>=2, whose extras this check does not follow"]),
        # An overridden package is held to its override, not to the pin.
        ({"app": ["jwt==2.8.0"]}, []),
    ],
)
def test_each_applicable_requirement_must_be_locked_at_a_version_it_allows(requires, expected):
    assert unmet(PINS, requires, {"jwt": SpecifierSet(">=2.15.0")}) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"jwt": SpecifierSet(">=2.15.0,<3")}, []),
        ({"jwt": SpecifierSet(">=2.16")}, ["jwt>=2.16, but the lock holds jwt==2.15.1"]),
        ({"gone": SpecifierSet(">=1")}, ["gone>=1, but the lock does not hold gone"]),
    ],
)
def test_the_lock_must_hold_each_override_at_a_version_it_allows(overrides, expected):
    assert override_problems(PINS, overrides) == expected


@pytest.mark.parametrize(
    ("requires", "expected"),
    [
        # The client still pins the old version: the override is needed.
        ({"app": ["jwt==2.8.0"]}, []),
        # The client now allows the locked version: the override lifts nothing.
        ({"app": ["jwt>=2.8.0"]}, ["jwt"]),
        ({"app": ["lib>=2"]}, ["jwt"]),
        # A requirement that does not apply to the image contradicts nothing.
        ({"app": ['jwt==2.8.0; sys_platform == "win32"']}, ["jwt"]),
    ],
)
def test_an_override_no_requirement_contradicts_is_stale(requires, expected):
    assert stale_overrides(PINS, requires, {"jwt": SpecifierSet(">=2.15.0")}) == expected


def test_overrides_are_read_as_names_and_specifiers(tmp_path):
    path = tmp_path / "requirements-overrides.txt"
    path.write_text("# why\nPyJWT>=2.15.0,<3  # advisories\n\nrequests>=2.33.0\n", encoding="utf-8")

    assert read_overrides(path) == {"pyjwt": SpecifierSet(">=2.15.0,<3"), "requests": SpecifierSet(">=2.33.0")}


@pytest.mark.parametrize("line", ["pyjwt", "pyjwt==2.15.1; python_version >= '3.11'", "pyjwt[crypto]>=2.15"])
def test_an_override_must_be_a_bare_name_and_a_range(tmp_path, line):
    # Without a version it lifts nothing; a marker or an extra would apply it
    # to only part of what the lock is resolved for, which this check cannot see.
    path = tmp_path / "requirements-overrides.txt"
    path.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="override"):
        read_overrides(path)
