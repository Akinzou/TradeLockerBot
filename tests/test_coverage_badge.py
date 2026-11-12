"""Fitness function: the README's coverage badge states the floor CI enforces.

The badge is a fixed image rather than one a service redraws after each run,
so nothing else would keep its number honest. Tying it to ``fail_under``
means the badge can never claim more than a green CI has proved: raising one
without the other fails here, and coverage below the floor fails CI.
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BADGE = re.compile(r"https://img\.shields\.io/badge/coverage-(\d+(?:\.\d+)?)%25-brightgreen")


def _floor():
    with open(REPO_ROOT / "pyproject.toml", "rb") as file:
        return tomllib.load(file)["tool"]["coverage"]["report"]["fail_under"]


def _tests_job():
    workflow = (REPO_ROOT / ".github/workflows/python-package.yml").read_text(encoding="utf-8")
    # The jobs are the two-space keys under `jobs:`; the tests job runs until
    # the next one.
    return re.search(r"^  tests:\n(.*?)(?=^  \S)", workflow, flags=re.M | re.S).group(1)


def test_the_badge_beside_the_title_states_the_enforced_floor():
    title = next(line for line in (REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
                 if line.startswith("# "))
    badge = BADGE.search(title)

    assert badge, title
    assert float(badge.group(1)) == _floor()


def test_the_tests_job_fails_a_run_below_the_floor():
    job = _tests_job()
    commands = [line.strip().removeprefix("run: ") for line in job.splitlines()]

    # `coverage report` is what applies fail_under; `coverage run` alone
    # would measure and never fail. A whole line, since the report written
    # to the summary is allowed to fail and so enforces nothing. In the
    # tests job, after the run, where the measurement is; and no step there
    # may turn a failure into a pass.
    assert "python -m coverage run -m pytest" in commands
    assert "python -m coverage report" in commands
    assert commands.index("python -m coverage run -m pytest") < commands.index("python -m coverage report")
    assert "continue-on-error" not in job
