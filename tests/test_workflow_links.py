"""Fitness functions for what ties one file to another by name or version,
where a mismatch fails nothing on its own.

A workflow that runs after another names it in ``workflow_run``. Renamed
on one side only, the publish never triggers again, and the image or the
site goes stale with no red run to show it. The documentation's build
tools are pinned in ``requirements-docs.in`` and installed from the lock
compiled from it: a pin bumped without the lock would claim a version the
site is not built with (ADR 0031).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _name(path):
    return re.search(r"^name: (.+)$", path.read_text(encoding="utf-8"), flags=re.M).group(1).strip()


def _triggers(path):
    found = re.search(r"^\s+workflows: \[(.*)\]$", path.read_text(encoding="utf-8"), flags=re.M)
    return re.findall(r'"([^"]+)"', found.group(1)) if found else []


def _pins(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(re.match(r"^([A-Za-z0-9_.-]+)==(\S+)", line).groups()
                for line in lines if re.match(r"^[A-Za-z0-9_.-]+==", line))


def _canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def test_every_workflow_run_trigger_names_a_workflow():
    names = {_name(path) for path in WORKFLOWS.glob("*.yml")}
    triggers = {path.name: _triggers(path) for path in WORKFLOWS.glob("*.yml")}

    assert triggers["docker-image.yml"] and triggers["pages.yml"], triggers
    assert {path: [name for name in named if name not in names]
            for path, named in triggers.items()} == {path: [] for path in triggers}


def test_the_docs_lock_holds_every_pin_of_its_source():
    wanted = {_canonical(name): version for name, version in _pins(REPO_ROOT / "requirements-docs.in").items()}
    locked = {_canonical(name): version for name, version in _pins(REPO_ROOT / "requirements-docs.txt").items()}

    assert wanted
    assert {name: locked.get(name) for name in wanted} == wanted
