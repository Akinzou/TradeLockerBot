"""Fitness function: ``requirements-lock.txt`` is what the image installs, so
it must pin every package with hashes and still satisfy ``requirements.txt``.

``requirements.txt`` names what the bot needs; the lock fixes every package,
transitive ones included, to one version and its hashes. Without the lock,
each image build resolved ``fastapi`` and ``uvicorn`` afresh and let any
upstream release change the running code with no commit. The lock is
generated, never edited (see the command in its header); these tests catch a
requirement changed without regenerating it, which would otherwise surface
only as a failed image build or, worse, a stale pin that still installs.
"""

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests.characterization.fake_tradelocker import TRADELOCKER_VERSION

ROOT = Path(__file__).resolve().parent.parent
PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)")


def _lock():
    pins, hashes, name = {}, {}, None
    for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        if match := PIN.match(line):
            name = canonicalize_name(match["name"])
            pins[name] = match["version"]
            hashes[name] = 0
        elif line.strip().startswith("--hash=sha256:"):
            hashes[name] += 1
        elif line.strip() and not line.lstrip().startswith("#"):
            raise AssertionError(f"unexpected lock line: {line!r}")
    return pins, hashes


def _direct_requirements():
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            yield Requirement(line)


def test_every_locked_package_carries_hashes():
    pins, hashes = _lock()

    assert pins, "the lock pins nothing - the path is wrong, not the rule"
    assert {name for name, count in hashes.items() if count == 0} == set()


def test_the_lock_satisfies_every_direct_requirement():
    pins, _ = _lock()

    unsatisfied = [
        str(req) for req in _direct_requirements()
        if canonicalize_name(req.name) not in pins
        or not req.specifier.contains(pins[canonicalize_name(req.name)], prereleases=True)
    ]
    assert unsatisfied == []


def test_the_lock_pins_the_characterized_client_version():
    pins, _ = _lock()

    assert pins["tradelocker"] == TRADELOCKER_VERSION
