"""Exact console bytes, colour codes and reset lines included: the
characterization suite strips colours, so they are pinned here."""

import math

import pytest

from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.application.refusal import NoBalance, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import UnusableQuantity
from tradelocker_bot.domain.signal import InvalidSignal, Side

GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda c: c.locked(), "Normal: Locked\n"),
        (lambda c: c.closing("XAUUSD"), "Closing: XAUUSD\n"),
        (lambda c: c.order_retry(Side.SELL), f"{RED}Sell order was not successful, trying again...\n{RESET}\n"),
        (lambda c: c.order_placed(9001), f"{GREEN}Order placed successfully, order ID: 9001\n{RESET}\n"),
        (lambda c: c.unlocked(), "Normal: Unlocked\n"),
    ],
)
def test_prints_the_legacy_line(capsys, call, expected):
    call(PrintingConsole())

    assert capsys.readouterr().out == expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (InvalidSignal(2, "direction", "long", "buy or sell"),
         "line 2 (direction) is 'long', expected buy or sell"),
        (InvalidSignal(7, "inversion", None, "Invert or NonInvert"),
         "line 7 (inversion) is missing, expected Invert or NonInvert"),
        # Webhook text is printed escaped, so it cannot colour, rewrite or
        # forge the operator's log lines.
        (InvalidSignal(6, "action", "\x1b[92mopen\r", "open or close"),
         r"line 6 (action) is '\x1b[92mopen\r', expected open or close"),
        (InvalidSignal(4, "take profit", "9" * 100, "a whole number"),
         f"line 4 (take profit) is '{'9' * 40}'... (100 characters), expected a whole number"),
        # Refused once the broker answered (ADR 0009), in the same shape.
        (NoBalance(), "the account balance is missing or not a number, expected a number to size the position from"),
        (UnknownSymbol("GBPUSD"), "line 1 (symbol) is 'GBPUSD', expected an instrument the broker lists"),
        (UnknownSymbol("\x1b[2J" + "X" * 60),
         r"line 1 (symbol) is '\x1b[2J" + "X" * 36 + "'... (64 characters), expected an instrument the broker lists"),
        (UnusableQuantity(balance=10.0, quantity=0.0),
         "line 3 (lot) gives 0.0 at a balance of 10.0, expected a quantity above 0"),
        (UnusableQuantity(balance=1000, quantity=math.inf),
         "line 3 (lot) gives inf at a balance of 1000, expected a quantity above 0"),
        (UnusableQuantity(balance=-500.0, quantity=-0.05),
         "the account balance is -500.0, expected a positive number to size the position from"),
        (UnusableQuantity(balance=math.inf, quantity=math.inf),
         "the account balance is inf, expected a positive number to size the position from"),
    ],
)
def test_a_rejected_signal_names_the_line_and_shows_its_value_escaped(capsys, reason, expected):
    PrintingConsole().rejected(reason)

    assert capsys.readouterr().out == f"{RED}Signal rejected: {expected}\n{RESET}\n"
