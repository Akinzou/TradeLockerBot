"""Exact console bytes, colour codes and reset lines included: the
characterization suite strips colours, so they are pinned here."""

import pytest

from tradelocker_bot.adapters.console import PrintingConsole

GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda c: c.locked(), "Normal: Locked\n"),
        (lambda c: c.closing("XAUUSD"), "Closing: XAUUSD\n"),
        (lambda c: c.order_retry("sell"), f"{RED}Sell order was not successful, trying again...\n{RESET}\n"),
        (lambda c: c.order_placed(9001), f"{GREEN}Order placed successfully, order ID: 9001\n{RESET}\n"),
        (lambda c: c.unlocked(), "Normal: Unlocked\n"),
    ],
)
def test_prints_the_legacy_line(capsys, call, expected):
    call(PrintingConsole())

    assert capsys.readouterr().out == expected
