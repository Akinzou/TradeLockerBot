"""Fitness function: the lock holds everything its packages need, and each
override in ``requirements-overrides.txt`` is both honoured and still needed.

The image installs the lock with ``--no-deps``, because the overrides
contradict the ``tradelocker`` client's exact pins and pip would refuse them
(ADR 0017). pip therefore no longer checks that each locked package's
requirements are locked too; ``python -m tests.dependency_closure`` does, in
CI and inside the image, against the metadata of the installed lock. These
tests pin the rules it applies, and check the overrides against the lock
itself.
"""

import pytest
from packaging.specifiers import SpecifierSet

from tests.dependency_closure import (
    installed_requires,
    override_problems,
    read_overrides,
    stale_overrides,
    unmet,
)
from tests.dependency_lock import read_lock

LOCK = read_lock()
OVERRIDES = read_overrides()

# The CLI reads markers for the interpreter running it; the rules are pinned
# for a fixed one, so the tests do not depend on the machine.
LINUX_311 = {
    "python_version": "3.11",
    "python_full_version": "3.11.14",
    "sys_platform": "linux",
    "platform_system": "Linux",
}
PINS = {"app": "1.0", "lib": "2.0", "jwt": "2.15.1", "tradelocker": "0.56.2"}
JWT = {"jwt": SpecifierSet(">=2.15.0")}


def test_the_lock_holds_every_override_at_a_version_it_allows():
    assert OVERRIDES, "no overrides read - the path is wrong, not the rule"
    assert override_problems(LOCK.pins, OVERRIDES) == []


@pytest.mark.parametrize(
    ("requires", "expected"),
    [
        ({"app": ["lib>=2"]}, []),
        ({"app": ["Lib (>=1,<3)"]}, []),
        ({"app": ["lib>=3"]}, ["app needs lib>=3, the lock holds lib==2.0"]),
        ({"app": ["missing"]}, ["app needs missing, which the lock does not hold"]),
        ({"app": ['colorama; sys_platform == "win32"']}, []),
        ({"app": ['tomli; python_version < "3.11"']}, []),
        ({"app": ["missing; python_version >= '3.11'"]},
         ["app needs missing; python_version >= '3.11', which the lock does not hold"]),
        ({"app": ['crypto; extra == "crypto"']}, []),
        # An extra pulls in requirements this check does not follow.
        ({"app": ["lib[fast]>=2"]}, ["app needs lib[fast]>=2, whose extras this check does not follow"]),
        # The client's pin is what the override lifts.
        ({"tradelocker": ["jwt==2.8.0"]}, []),
        # Any other package's requirement on an overridden package still counts.
        ({"app": ["jwt<2.15"]}, ["app needs jwt<2.15, the lock holds jwt==2.15.1"]),
        ({"app": ["jwt>=2"]}, []),
    ],
)
def test_each_applicable_requirement_must_be_locked_at_a_version_it_allows(requires, expected):
    assert unmet(PINS, requires, JWT, LINUX_311) == expected


def test_markers_are_read_for_the_interpreter_given():
    requires = {"app": ['missing; python_version >= "3.12"']}

    assert unmet(PINS, requires, JWT, LINUX_311) == []
    assert unmet(PINS, requires, JWT, {**LINUX_311, "python_version": "3.12"}) != []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"jwt": SpecifierSet(">=2.15.0,<3")}, []),
        ({"jwt": SpecifierSet(">=2.16")}, ["override jwt>=2.16: the lock holds jwt==2.15.1"]),
        ({"gone": SpecifierSet(">=1")}, ["override gone>=1: the lock does not hold gone"]),
    ],
)
def test_the_lock_must_hold_each_override_at_a_version_it_allows(overrides, expected):
    assert override_problems(PINS, overrides) == expected


@pytest.mark.parametrize(
    ("requires", "overrides", "expected"),
    [
        # The client still pins the old version: the override is needed.
        ({"tradelocker": ["jwt==2.8.0"]}, JWT, []),
        # The client now allows the locked version: the override lifts nothing.
        ({"tradelocker": ["jwt>=2.8.0"]}, JWT, ["jwt"]),
        ({"tradelocker": ["lib>=2"]}, JWT, ["jwt"]),
        # Only the client's pins may be lifted, so another package's does not count.
        ({"app": ["jwt==2.8.0"]}, JWT, ["jwt"]),
        # A requirement that does not apply contradicts nothing.
        ({"tradelocker": ['jwt==2.8.0; sys_platform == "win32"']}, JWT, ["jwt"]),
        # An override the lock does not hold is reported as such, not as stale:
        # removing it would be the wrong advice.
        ({"tradelocker": ["jwt==2.8.0"]}, {**JWT, "gone": SpecifierSet(">=1")}, []),
    ],
)
def test_an_override_none_of_the_clients_requirements_contradicts_is_stale(requires, overrides, expected):
    assert stale_overrides(PINS, requires, overrides, LINUX_311) == expected


def _overrides_file(tmp_path, text):
    path = tmp_path / "requirements-overrides.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_overrides_are_read_as_names_and_specifiers(tmp_path):
    path = _overrides_file(tmp_path, "# why\nPyJWT>=2.15.0,<3  # advisories\n\nrequests>=2.33.0\n")

    assert read_overrides(path) == {"pyjwt": SpecifierSet(">=2.15.0,<3"), "requests": SpecifierSet(">=2.33.0")}


@pytest.mark.parametrize(
    "text",
    [
        # Without a version it lifts nothing; a marker or an extra would apply
        # it to only part of what the lock is resolved for.
        "pyjwt\n",
        "pyjwt==2.15.1; python_version >= '3.11'\n",
        "pyjwt[crypto]>=2.15\n",
        # uv would read these; this check would not, or would keep only one.
        "-c constraints.txt\n",
        "pyjwt>=2.15.0\nPyJWT<2.10\n",
    ],
)
def test_an_override_uv_would_read_differently_is_refused(tmp_path, text):
    with pytest.raises(ValueError, match="override"):
        read_overrides(_overrides_file(tmp_path, text))


def test_a_package_not_installed_at_its_locked_version_is_reported():
    requires, wrong = installed_requires({"pytest": "0.0.1", "zq7-not-installed": "1.0"})

    assert wrong == ["pytest==0.0.1 is installed at " + pytest.__version__,
                     "zq7-not-installed==1.0 is not installed"]
    assert list(requires) == ["pytest"]
