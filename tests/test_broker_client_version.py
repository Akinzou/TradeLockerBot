"""Fitness function: the broker client is pinned to the version the
characterization fake mirrors.

The fake copies that version's signatures, defaults and failure modes, and the
pins compare full requests with defaults filled in. An unpinned client lets an
upstream release change a default or a signature: the image would then ship a
different broker request, while CI fails on pins nobody touched. Pinning makes
a version move a reviewed change. Kept outside ``tests/characterization`` so a
version bump never reads as an edit to the behaviour pins.

The image itself is checked by the CI ``docker-build`` job; this test covers
the requirement and the environment the suite runs in.
"""

from importlib.metadata import version

from packaging.requirements import Requirement

from tests.characterization.fake_tradelocker import TRADELOCKER_VERSION
from tests.dependency_lock import requirement_lines


def _requirements():
    # Parsed rather than matched as text, so a comment cannot satisfy the test
    # and an equivalent spelling (spaces, markers, case) cannot fail it.
    return [Requirement(line) for line in requirement_lines()]


def test_requirements_pin_the_characterized_client_version():
    [client] = [req for req in _requirements() if req.name.lower() == "tradelocker"]

    assert str(client.specifier) == f"=={TRADELOCKER_VERSION}"


def test_suite_runs_against_the_characterized_client_version():
    assert version("tradelocker") == TRADELOCKER_VERSION
