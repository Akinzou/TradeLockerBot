"""Fitness function: the domain imports only pure standard-library modules and
reads no builtin that reaches I/O, the interpreter or code by name.

Imports are checked against a true allow-list. Filtering
``sys.stdlib_module_names`` through a deny-list of I/O modules let
``datetime`` (the clock), ``concurrent``, ``shelve`` and ``imaplib`` through,
because every module nobody listed was allowed. Here, anything not named below
fails, including any third-party package and any other layer. Adding a module
is a reviewed decision.

Builtins need no import, so they get their own check. It guards against
accidents, not against deliberate evasion (``type(x).__subclasses__`` and
similar introspection still reach anything); review covers that.
"""

import ast
from pathlib import Path

DOMAIN = Path(__file__).resolve().parent.parent / "tradelocker_bot" / "domain"
DOMAIN_PACKAGE = "tradelocker_bot.domain"

# Only modules whose every public name is free of I/O, clock, randomness and
# concurrency, so allowing the module cannot let an impure call in through a
# side door (`datetime` is out because of `datetime.now`).
PURE_STDLIB = {
    "__future__", "abc", "collections", "dataclasses", "decimal", "enum",
    "fractions", "functools", "itertools", "math", "numbers", "operator",
    "re", "string", "types", "typing",
}

# Builtins that do I/O or stop the process (`open`, `print`, `input`, `help`,
# `exit` and the other `site` helpers), run or import code by name, or hand
# out the namespace where the others live (`globals`, `vars`, `locals`).
IMPURE_BUILTINS = {
    "__builtins__", "__import__", "breakpoint", "compile", "copyright",
    "credits", "eval", "exec", "exit", "globals", "help", "input", "license",
    "locals", "open", "print", "quit", "vars",
}


def _package_of(path):
    # Both `domain/x.py` and `domain/__init__.py` live in package `...domain`.
    return path.relative_to(DOMAIN.parent.parent).parts[:-1]


def _imported_modules(tree, path):
    package = _package_of(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            # Resolve `from .. import x` against the real package, so a relative
            # import cannot step outside the domain unnoticed.
            base = package[: len(package) - (node.level - 1)]
            yield ".".join(base + ((node.module,) if node.module else ()))
        elif isinstance(node, ast.ImportFrom):
            yield node.module


def _forbidden_imports(tree, path):
    for module in _imported_modules(tree, path):
        is_domain = module == DOMAIN_PACKAGE or module.startswith(DOMAIN_PACKAGE + ".")
        if not is_domain and module.split(".")[0] not in PURE_STDLIB:
            yield module


def _impure_builtins_read(tree, path):
    # Reads only: a field such as `Candle.open` is a Store and must stay legal
    # in a trading domain, while a Load catches both calls and aliasing
    # (`read = open`).
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in IMPURE_BUILTINS:
            yield node.id


def _violations(rule):
    files = sorted(DOMAIN.rglob("*.py"))
    assert files, "no domain modules found - the path is wrong, not the rule"
    return {
        f"{path.relative_to(DOMAIN.parent.parent)}: {name}"
        for path in files
        for name in rule(ast.parse(path.read_text(encoding="utf-8")), path)
    }


def test_domain_imports_only_allow_listed_modules():
    assert _violations(_forbidden_imports) == set()


def test_domain_reads_no_impure_builtins():
    assert _violations(_impure_builtins_read) == set()
