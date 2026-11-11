"""``parse_signal``: a webhook payload becomes what it asks for, or the first
line that stops it, before anything else happens (ADR 0008)."""

import pytest

from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.result import Err, Ok
from tradelocker_bot.domain.signal import (
    CloseSignal,
    InvalidSignal,
    OpenSignal,
    Side,
    parse_signal,
)


def lines(symbol="XAUUSD", direction="buy", lot="0.01/100", tp="500", sl="1000", action="open", invert="NonInvert"):
    return [symbol, direction, lot, tp, sl, action, invert]


SIZING = LotSizing(base_lot=0.01, balance_step=100.0)


def opened(side, take_profit=500, stop_loss=1000, sizing=SIZING):
    return Ok(OpenSignal(symbol="XAUUSD", side=side, sizing=sizing, take_profit=take_profit, stop_loss=stop_loss))


@pytest.mark.parametrize(
    ("direction", "invert", "side"),
    [
        ("buy", "NonInvert", Side.BUY),
        ("sell", "NonInvert", Side.SELL),
        ("buy", "Invert", Side.SELL),
        ("sell", "Invert", Side.BUY),
    ],
)
def test_open_resolves_the_side_to_trade(direction, invert, side):
    assert parse_signal(lines(direction=direction, invert=invert)) == opened(side)


@pytest.mark.parametrize(
    ("direction", "invert", "side"),
    [
        ("Buy", "Invert", Side.SELL),
        ("BUY", "NonInvert", Side.BUY),
        (" sell ", "NonInvert", Side.SELL),
        ("\tSell", "Invert", Side.BUY),
    ],
)
def test_direction_ignores_case_and_surrounding_spaces(direction, invert, side):
    assert parse_signal(lines(direction=direction, invert=invert)) == opened(side)


@pytest.mark.parametrize("action", ["Open", "OPEN", " open", "open "])
def test_action_ignores_case_and_surrounding_spaces(action):
    assert parse_signal(lines(action=action)) == opened(Side.BUY)


@pytest.mark.parametrize("action", ["close", "Close", " CLOSE "])
def test_close_needs_only_the_symbol_and_the_action(action):
    payload = [*lines(direction="long", lot="x", tp="", sl="?", action=action, invert="Sideways")]

    assert parse_signal(payload) == Ok(CloseSignal(symbol="XAUUSD"))


def test_close_without_a_seventh_line_is_complete():
    assert parse_signal(lines(action="close")[:6]) == Ok(CloseSignal(symbol="XAUUSD"))


@pytest.mark.parametrize(
    ("tp", "sl", "take_profit", "stop_loss"),
    [(" 500 ", "+1000", 500, 1000), ("0", "-5", 0, -5)],
)
def test_offsets_keep_what_int_accepts(tp, sl, take_profit, stop_loss):
    # Not on the defect list, so accepted exactly as before (ADR 0008).
    assert parse_signal(lines(tp=tp, sl=sl)) == opened(Side.BUY, take_profit, stop_loss)


def test_lines_after_the_seventh_are_ignored():
    assert parse_signal([*lines(), "extra"]) == opened(Side.BUY)


def rejected(line, field, value, expected):
    return Err(InvalidSignal(line=line, field=field, value=value, expected=expected))


DIRECTION = "buy or sell"
LOT = "<lot>/<balance step>, two positive numbers"
NUMBER = "a whole number"
ACTION = "open or close"
INVERT = "Invert or NonInvert"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ([], rejected(1, "symbol", None, "an instrument name")),
        (["   ", "buy"], rejected(1, "symbol", "   ", "an instrument name")),
        (["XAUUSD"], rejected(6, "action", None, ACTION)),
        (lines(action="hold"), rejected(6, "action", "hold", ACTION)),
        (lines(action="opne", direction="long"), rejected(6, "action", "opne", ACTION)),
        (lines(direction="long"), rejected(2, "direction", "long", DIRECTION)),
        (lines(direction=""), rejected(2, "direction", "", DIRECTION)),
        (lines(lot="0.01"), rejected(3, "lot", "0.01", LOT)),
        (lines(lot="abc/100"), rejected(3, "lot", "abc/100", LOT)),
        (lines(lot="0.01/100/2"), rejected(3, "lot", "0.01/100/2", LOT)),
        (lines(lot="0.01/0"), rejected(3, "lot", "0.01/0", LOT)),
        (lines(lot="0/100"), rejected(3, "lot", "0/100", LOT)),
        (lines(lot="-0.01/100"), rejected(3, "lot", "-0.01/100", LOT)),
        (lines(lot="inf/100"), rejected(3, "lot", "inf/100", LOT)),
        (lines(lot="1e999/1"), rejected(3, "lot", "1e999/1", LOT)),
        (lines(lot="nan/100"), rejected(3, "lot", "nan/100", LOT)),
        (lines(lot="0.01/-100"), rejected(3, "lot", "0.01/-100", LOT)),
        (lines(tp="5x"), rejected(4, "take profit", "5x", NUMBER)),
        (lines(tp="500.0"), rejected(4, "take profit", "500.0", NUMBER)),
        (lines(sl="1e3"), rejected(5, "stop loss", "1e3", NUMBER)),
        (lines(sl="9" * 10_000), rejected(5, "stop loss", "9" * 10_000, NUMBER)),
        (lines(invert="Sideways"), rejected(7, "inversion", "Sideways", INVERT)),
        (lines(invert="invert"), rejected(7, "inversion", "invert", INVERT)),
        (lines(invert=" Invert"), rejected(7, "inversion", " Invert", INVERT)),
        (lines()[:6], rejected(7, "inversion", None, INVERT)),
        (lines(direction="long", lot="x"), rejected(2, "direction", "long", DIRECTION)),
    ],
)
def test_reports_the_first_line_that_stops_the_signal(payload, expected):
    assert parse_signal(payload) == expected


@pytest.mark.parametrize("length", range(1, 6))
def test_a_payload_cut_before_the_action_is_rejected_at_the_action(length):
    assert parse_signal(lines()[:length]) == rejected(6, "action", None, ACTION)


def test_side_opposite():
    assert (Side.BUY.opposite(), Side.SELL.opposite()) == (Side.SELL, Side.BUY)
