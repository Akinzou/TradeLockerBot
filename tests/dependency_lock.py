"""Reads ``requirements.txt`` and ``requirements-lock.txt`` for the fitness
tests and the CI checks, so all of them read the files the same way.

Run as ``python -m tests.dependency_lock`` from the repository root, it
compares installed packages with the lock:

- ``--freeze IMAGE --base BASE --exact``: a ``pip freeze --all`` of the
  image must hold the locked set, and nothing else that its base image
  (``BASE``, frozen the same way) does not already hold at that version.
- no arguments: this environment must hold every locked package at its
  locked version; the dev tools may add more.

Standard library only, because the CI runner's own Python checks the image
without installing anything.
"""

import argparse
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
LOCK = ROOT / "requirements-lock.txt"

PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)")
DIRECT = "-r requirements.txt"


def canonical(name):
    """The PEP 503 normalized name, so ``PyJWT`` and ``pyjwt`` are one package."""
    return re.sub(r"[-_.]+", "-", name).lower()


class Lock:
    def __init__(self, pins, hashes, direct):
        self.pins = pins
        self.hashes = hashes
        self.direct = direct


def read_lock(path=LOCK):
    """Pins, hash counts and the names the lock marks as direct requirements.

    Any line that is not a pin, a hash, an annotation or a comment fails, so a
    format the parser does not understand cannot drop a package unnoticed.
    """
    pins, hashes, direct, name = {}, {}, set(), None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if match := PIN.match(line):
            name = canonical(match["name"])
            pins[name], hashes[name] = match["version"], 0
        elif stripped.startswith("--hash=sha256:") and name is not None:
            hashes[name] += 1
        elif stripped.startswith("# via") and name is not None:
            # uv writes a package's sources after its hashes.
            if DIRECT in stripped:
                direct.add(name)
        elif stripped and not stripped.startswith("#"):
            raise ValueError(f"{path.name}:{number}: unexpected lock line: {line!r}")
    return Lock(pins, hashes, direct)


def requirement_lines(path=REQUIREMENTS):
    """Requirement strings, without comments, blank lines or pip options."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            yield line


def _freeze_pins(text):
    return {
        canonical(match["name"]): match["version"]
        for line in text.splitlines()
        if (match := PIN.match(line))
    }


def mismatches(installed, lock_pins, exact, base=None):
    # The base image's own packages (pip, setuptools, wheel and what they
    # need) are not ours to lock; anything else, or a base package at
    # another version, is.
    base = base or {}
    missing = {f"{n}=={v}" for n, v in lock_pins.items() if installed.get(n) != v}
    extra = {f"{n}=={v}" for n, v in installed.items() if n not in lock_pins and base.get(n) != v}
    return sorted(missing), sorted(extra) if exact else []


def _installed_here(names):
    found = {}
    for name in names:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            pass
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--freeze", type=Path, help="pip freeze --all output to check instead of this environment")
    parser.add_argument("--base", type=Path, help="pip freeze --all of the base image, whose packages are allowed")
    parser.add_argument("--exact", action="store_true", help="also fail on packages the lock does not list")
    args = parser.parse_args(argv)
    lock = read_lock()
    if args.freeze:
        installed = _freeze_pins(args.freeze.read_text(encoding="utf-8"))
    else:
        installed = _installed_here(lock.pins)
    base = _freeze_pins(args.base.read_text(encoding="utf-8")) if args.base else {}
    missing, extra = mismatches(installed, lock.pins, args.exact, base)
    print(f"locked, not installed at that version: {missing}")
    print(f"installed, not locked: {extra}")
    return 1 if missing or extra else 0


if __name__ == "__main__":
    sys.exit(main())
