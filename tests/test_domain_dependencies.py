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
import symtable
from pathlib import Path

import pytest

DOMAIN = Path(__file__).resolve().parent.parent / "tradelocker_bot" / "domain"
DOMAIN_PACKAGE = "tradelocker_bot.domain"

# Modules for values, types and arithmetic; whole modules that do I/O or read
# the clock, randomness or concurrency stay out (`datetime` because of
# `datetime.now`). A few names inside the allowed ones still reach code or
# shared state (`typing.get_type_hints`, `types.FunctionType`,
# `decimal.getcontext`); review covers those, as it does deliberate evasion.
PURE_STDLIB = {
    "__future__", "abc", "collections", "dataclasses", "decimal", "enum",
    "fractions", "functools", "itertools", "math", "numbers", "operator",
    "re", "string", "types", "typing",
}

# Builtins that do I/O or stop the process (`open`, `print`, `input`, `help`,
# `exit` and the other `site` helpers), run or import code by name, or hand
# out the namespace where the others live (`globals`, `vars`, `locals`).
# `__loader__` and `__spec__` are module globals rather than builtins, listed
# because they read files themselves; `__file__` is only a string.
IMPURE_BUILTINS = {
    "__builtins__", "__import__", "__loader__", "__spec__", "breakpoint",
    "compile", "copyright", "credits", "eval", "exec", "exit", "globals",
    "help", "input", "license", "locals", "open", "print", "quit", "vars",
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


def _forbidden_imports(source, path):
    for module in _imported_modules(ast.parse(source), path):
        is_domain = module == DOMAIN_PACKAGE or module.startswith(DOMAIN_PACKAGE + ".")
        if not is_domain and module.split(".")[0] not in PURE_STDLIB:
            yield module


def _scopes(table):
    yield table
    for child in table.get_children():
        yield from _scopes(child)


def _impure_builtins_read(source, path):
    # symtable rather than matching names in the syntax tree: OHLC code needs
    # parameters and locals called `open`, and only the compiler's own scope
    # resolution tells those apart from a read of the builtin, which covers
    # calls and aliasing (`read = open`) alike. A read that resolves through
    # module scope is flagged even when the module rebinds the name: shadowing
    # these builtins at module level is itself out, which keeps the rule
    # independent of statement order and dead branches.
    for scope in _scopes(symtable.symtable(source, str(path), "exec")):
        for symbol in scope.get_symbols():
            if symbol.get_name() in IMPURE_BUILTINS and symbol.is_referenced() and symbol.is_global():
                yield symbol.get_name()


def _violations(rule):
    files = sorted(DOMAIN.rglob("*.py"))
    assert files, "no domain modules found - the path is wrong, not the rule"
    return {
        f"{path.relative_to(DOMAIN.parent.parent)}: {name}"
        for path in files
        for name in rule(path.read_text(encoding="utf-8"), path)
    }


def test_domain_imports_only_allow_listed_modules():
    assert _violations(_forbidden_imports) == set()


def test_domain_reads_no_impure_builtins():
    assert _violations(_impure_builtins_read) == set()


# The domain itself uses none of these, so the checks above would pass even if
# the rules caught nothing. These sources prove each rule both fires and stays
# quiet where it should.
PROBE = DOMAIN / "probe.py"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import datetime", ["datetime"]),
        ("from concurrent import futures", ["concurrent"]),
        ("import pandas", ["pandas"]),
        ("from .. import adapters", ["tradelocker_bot"]),
        ("from ..application import x", ["tradelocker_bot.application"]),
        ("import math\nfrom dataclasses import dataclass", []),
        ("from . import lot_sizing\nfrom .lot_sizing import LotSizing", []),
        ("import tradelocker_bot.domain.lot_sizing", []),
    ],
)
def test_import_rule_on_probe_sources(source, expected):
    assert list(_forbidden_imports(source, PROBE)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("print(1)", ["print"]),
        ("read = open", ["open"]),
        ("def f():\n    def g():\n        return open\n    return g", ["open"]),
        ("class C:\n    shown = print", ["print"]),
        ("print(1)\nprint = None", ["print"]),
        ("if False:\n    def open(): pass\nopen('x')", ["open"]),
        ("__loader__.get_data('x')", ["__loader__"]),
        ("exit()", ["exit"]),
        ("class Candle:\n    open: float\n    close: float", []),
        ("def body(open, close):\n    return abs(close - open)", []),
        ("def f():\n    input = 2\n    return input", []),
        ("def f(candle):\n    return candle.open", []),
    ],
)
def test_builtin_rule_on_probe_sources(source, expected):
    assert list(_impure_builtins_read(source, PROBE)) == expected
