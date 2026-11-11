"""Checks what pip no longer checks when the image installs the lock with
``--no-deps`` (ADR 0017): that every locked package's requirements are
locked too, and that ``requirements-overrides.txt`` is honoured and needed.

Run as ``python -m tests.dependency_closure`` from the repository root, after
installing the lock. It reads each locked package's requirements from the
installed metadata, so it first refuses an environment whose versions are
not the locked ones: their requirements could differ.

Kept apart from ``tests/dependency_lock.py``, which must stay standard
library only, because this check needs ``packaging`` to read requirements.
"""

import sys
from importlib.metadata import PackageNotFoundError, distribution

from packaging.requirements import Requirement

from tests.dependency_lock import ROOT, canonical, read_lock, requirement_lines

OVERRIDES = ROOT / "requirements-overrides.txt"

# The platform the lock is resolved for (ADR 0007). Markers are read for it,
# not for the machine running the check: a Windows-only requirement is not
# the image's, and one for Python 3.11 is, even on a 3.12 runner.
IMAGE = {
    "python_version": "3.11",
    "python_full_version": "3.11.0",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "os_name": "posix",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "extra": "",
}


def read_overrides(path=OVERRIDES):
    """Each override as its normalized name and the versions it allows."""
    overrides = {}
    for line in requirement_lines(path):
        req = Requirement(line)
        if not req.specifier or req.marker or req.extras:
            raise ValueError(f"{path.name}: an override is a name and a version range only: {line!r}")
        overrides[canonical(req.name)] = req.specifier
    return overrides


def _applicable(requires, environment):
    for package, texts in sorted(requires.items()):
        for text in texts:
            req = Requirement(text)
            if req.marker is None or req.marker.evaluate(environment):
                yield package, text, req, canonical(req.name)


def unmet(pins, requires, overrides, environment=IMAGE):
    """Requirements of locked packages the lock does not satisfy.

    An overridden package is held to its override instead, as uv held it
    when it compiled the lock; ``override_problems`` checks that.
    """
    problems = []
    for package, text, req, name in _applicable(requires, environment):
        if req.extras:
            problems.append(f"{package} needs {text}, whose extras this check does not follow")
        elif name not in pins:
            problems.append(f"{package} needs {text}, which the lock does not hold")
        elif name not in overrides and not req.specifier.contains(pins[name], prereleases=True):
            problems.append(f"{package} needs {text}, the lock holds {name}=={pins[name]}")
    return problems


def override_problems(pins, overrides):
    """Overrides the lock does not hold, or holds at a version they exclude."""
    problems = []
    for name, specifier in sorted(overrides.items()):
        if name not in pins:
            problems.append(f"{name}{specifier}, but the lock does not hold {name}")
        elif not specifier.contains(pins[name], prereleases=True):
            problems.append(f"{name}{specifier}, but the lock holds {name}=={pins[name]}")
    return problems


def stale_overrides(pins, requires, overrides, environment=IMAGE):
    """Overrides that lift nothing: no applicable requirement excludes the
    locked version. Such an override would hide a later pin that matters."""
    contradicted = {
        name for _, _, req, name in _applicable(requires, environment)
        if name in overrides and name in pins and not req.specifier.contains(pins[name], prereleases=True)
    }
    return sorted(set(overrides) - contradicted)


def _installed_requires(pins):
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
    requires, wrong = _installed_requires(lock.pins)
    if wrong:
        print("install the lock first:", *wrong, sep="\n  ")
        return 1
    problems = unmet(lock.pins, requires, overrides) + override_problems(lock.pins, overrides)
    stale = stale_overrides(lock.pins, requires, overrides)
    problems += [f"override {name} lifts nothing; remove it" for name in stale]
    print(f"requirements the lock does not meet: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
