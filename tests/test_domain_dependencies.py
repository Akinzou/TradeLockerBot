"""Fitness function: the domain imports only side-effect-free standard library.

An allow-list instead of a deny-list of known libraries: any new third-party
package, any other layer, and any stdlib module that performs I/O or reads the
clock fails here, so the rule in docs/architecture.md holds by construction.
"""

import ast
import sys
from pathlib import Path

DOMAIN = Path(__file__).resolve().parent.parent / "tradelocker_bot" / "domain"
DOMAIN_PACKAGE = "tradelocker_bot.domain"

# Standard-library modules that reach outside the process (network, files,
# subprocesses, threads) or read the clock. Those belong behind a port.
IO_STDLIB = {
    "asyncio", "ftplib", "glob", "http", "io", "logging", "mmap", "multiprocessing",
    "os", "pathlib", "random", "secrets", "select", "selectors", "shutil", "signal",
    "smtplib", "socket", "socketserver", "sqlite3", "ssl", "subprocess", "sys",
    "tempfile", "threading", "time", "urllib", "uuid",
}


def _package_of(path):
    # Both `domain/x.py` and `domain/__init__.py` live in package `...domain`.
    return path.relative_to(DOMAIN.parent.parent).parts[:-1]


def _imported_modules(path):
    package = _package_of(path)
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            # Resolve `from .. import x` against the real package, so a relative
            # import cannot step outside the domain unnoticed.
            base = package[: len(package) - (node.level - 1)]
            yield ".".join(base + ((node.module,) if node.module else ()))
        elif isinstance(node, ast.ImportFrom):
            yield node.module


def _is_allowed(module):
    if module == DOMAIN_PACKAGE or module.startswith(DOMAIN_PACKAGE + "."):
        return True
    top_level = module.split(".")[0]
    return top_level in sys.stdlib_module_names and top_level not in IO_STDLIB


def test_domain_imports_only_pure_standard_library():
    files = sorted(DOMAIN.rglob("*.py"))
    violations = {
        f"{path.relative_to(DOMAIN.parent.parent)}: {module}"
        for path in files
        for module in _imported_modules(path)
        if not _is_allowed(module)
    }

    assert files, "no domain modules found - the path is wrong, not the rule"
    assert violations == set()
