"""Checks what pip no longer checks when the image installs the lock with
``--no-deps`` (ADR 0017): that every locked package's requirements are
locked too, and that ``requirements-overrides.txt`` is honoured and needed.

Run as ``python -m tests.dependency_closure`` from the repository root, after
installing the lock: CI runs it in the ``tests`` job and inside the built
image. It reads each locked package's requirements from the installed
metadata, so it first refuses an environment whose versions are not the
locked ones: their requirements could differ. Markers are evaluated for the
interpreter running the check. Inside the image that is the image's own,
which is the one that matters; on the 3.12 runner it catches a requirement
only 3.12 needs.

Kept apart from ``tests/dependency_lock.py``, which must stay standard
library only, because this check needs ``packaging`` to read requirements.
"""

import sys
from importlib.metadata import PackageNotFoundError, distribution

from packaging.requirements import Requirement

from tests.dependency_lock import ROOT, canonical, read_lock

OVERRIDES = ROOT / "requirements-overrides.txt"

# The only package whose requirements an override may lift. uv applies an
# override to every requirement on that package, so without this limit a
# needed override would also hide a later, unrelated package's requirement
# that the locked version breaks.
CLIENT = "tradelocker"


def read_overrides(path=OVERRIDES):
    """Each override as its normalized name and the versions it allows.

    Anything uv would read differently from this check is refused: a pip
    option, a second line for the same package, a line without a version, a
    marker or an extra.
    """
    overrides = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            raise ValueError(f"{path.name}: an override is not a pip option: {line!r}")
        req = Requirement(line)
        name = canonical(req.name)
        if not req.specifier or req.marker or req.extras:
            raise ValueError(f"{path.name}: an override is a name and a version range only: {line!r}")
        if name in overrides:
            raise ValueError(f"{path.name}: a second override for {name}: {line!r}")
        overrides[name] = req.specifier
    return overrides


def _applicable(requires, environment):
    env = {"extra": "", **(environment or {})}
    for package, texts in sorted(requires.items()):
        for text in texts:
            req = Requirement(text)
            if req.marker is None or req.marker.evaluate(env):
                yield package, text, req, canonical(req.name)


def _lifted(package, name, overrides):
    return package == CLIENT and name in overrides


def unmet(pins, requires, overrides, environment=None):
    """Requirements of locked packages the lock does not satisfy, except the
    client's requirements that an override lifts; ``override_problems``
    holds those packages to their overrides instead."""
    problems = []
    for package, text, req, name in _applicable(requires, environment):
        if req.extras:
            problems.append(f"{package} needs {text}, whose extras this check does not follow")
        elif name not in pins:
            problems.append(f"{package} needs {text}, which the lock does not hold")
        elif not req.specifier.contains(pins[name], prereleases=True) and not _lifted(package, name, overrides):
            problems.append(f"{package} needs {text}, the lock holds {name}=={pins[name]}")
    return problems


def override_problems(pins, overrides):
    """Overrides the lock does not hold, or holds at a version they exclude."""
    problems = []
    for name, specifier in sorted(overrides.items()):
        if name not in pins:
            problems.append(f"override {name}{specifier}: the lock does not hold {name}")
        elif not specifier.contains(pins[name], prereleases=True):
            problems.append(f"override {name}{specifier}: the lock holds {name}=={pins[name]}")
    return problems


def stale_overrides(pins, requires, overrides, environment=None):
    """Overrides of locked packages that lift nothing: none of the client's
    applicable requirements excludes the locked version. An override the
    lock does not hold is ``override_problems``' to report, not this."""
    lifting = {
        name for package, _, req, name in _applicable(requires, environment)
        if _lifted(package, name, overrides) and name in pins
        and not req.specifier.contains(pins[name], prereleases=True)
    }
    return sorted(name for name in overrides if name in pins and name not in lifting)


def installed_requires(pins):
    """Each locked package's installed requirements, and what is not
    installed at its locked version."""
    requires, wrong = {}, []
    for name, locked in pins.items():
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            wrong.append(f"{name}=={locked} is not installed")
            continue
        if dist.version != locked:
            wrong.append(f"{name}=={locked} is installed at {dist.version}")
        requires[name] = dist.requires or []
    return requires, wrong


def main():
    lock = read_lock()
    overrides = read_overrides()
    requires, wrong = installed_requires(lock.pins)
    if wrong:
        print("install the lock first:", *wrong, sep="\n  ")
        return 1
    problems = unmet(lock.pins, requires, overrides) + override_problems(lock.pins, overrides)
    problems += [
        f"override {name} lifts none of {CLIENT}'s requirements; remove it"
        for name in stale_overrides(lock.pins, requires, overrides)
    ]
    if problems:
        print("the lock and its overrides do not fit what the packages need:", *problems, sep="\n  ")
        return 1
    print(f"all {len(lock.pins)} locked packages have what they need; every override is honoured and needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
