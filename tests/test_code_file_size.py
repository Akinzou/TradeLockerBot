"""Fitness function: no code file git would commit may exceed the size budget.

Kept as a test rather than a lint plugin so it runs with zero extra tooling
and fails in the same place developers already look. The candidate list comes
from git (tracked plus untracked-but-not-ignored files), so virtualenvs and
caches never trip it while a new, not-yet-staged file still does.
"""

import subprocess
from pathlib import Path

MAX_LINES = 300
CODE_SUFFIXES = {".py", ".sh", ".ps1"}
REPO_ROOT = Path(__file__).resolve().parent.parent


def _committable_code_files():
    # -z keeps non-ASCII paths unquoted; quoted paths would end in `"` and be
    # silently skipped by the suffix filter.
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    paths = (REPO_ROOT / name for name in listing if Path(name).suffix in CODE_SUFFIXES)
    # Deleted from the working tree but still in the index: nothing to measure.
    return [path for path in paths if path.is_file()]


def _line_count(path):
    # Byte-level count works for UTF-8 and UTF-16 alike, where decoding as
    # UTF-8 would crash on files saved by Windows PowerShell.
    data = path.read_bytes()
    return data.count(b"\n") + (1 if data and not data.endswith((b"\n", b"\n\x00")) else 0)


def test_code_files_fit_the_size_budget():
    files = _committable_code_files()
    oversized = {
        str(path.relative_to(REPO_ROOT)): count
        for path in files
        if (count := _line_count(path)) > MAX_LINES
    }

    assert files, "no code files found - the git listing is broken, not the budget"
    assert oversized == {}
