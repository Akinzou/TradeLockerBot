"""Exact broker call sequences and exact exception types on the raising paths
of ``handle_position_normal``, and inputs whose problems legacy code never
reaches.

The success-path pins fix the order of broker calls, but a restructure could
still move a validation earlier or later on a failing signal: resolving the
trade side before the second instrument lookup, or for actions that never
use it, or reading the balance strictly before the lot is parsed. Each of
those changes which broker calls happen before the failure, or whether it
fails. The type is compared exactly, because ``pytest.raises`` alone would also
accept a new subclass such as an ``InvalidSignal(ValueError)``.

Where two raise sites share a type, ``match`` names the site that must fail.
"""

import pytest
from tradelocker.exceptions import TLAPIOrderException

from tests.characterization.fake_tradelocker import NO_BALANCE_FIELD
from tests.characterization.harness import (
    BALANCE,
    CLOSE,
    LOOKUP,
    ORDER,
    POSITIONS,
    XAUUSD_ID,
    broker,
    handle,
    order_rejection,
    payload,
)

UNKNOWN_LOOKUP = ("get_instrument_id_from_symbol_name", "GBPUSD")
LOT_PARSE = "could not convert string to float"

TRUNCATED = [
    (f"payload truncated to {length} lines", {}, payload()[:length], IndexError, None, [])
    for length in range(7)
]


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "match", "expected"),
    [
        *TRUNCATED,
        ("non-numeric take profit", {}, payload(tp="5x"), ValueError, "int", []),
        ("non-numeric stop loss", {}, payload(sl="1e3"), ValueError, "int", []),
        ("lot without a step", {"open_positions": [XAUUSD_ID]}, payload(lot="0.01"),
         ValueError, "not enough values", [BALANCE]),
        ("non-numeric lot", {"open_positions": [XAUUSD_ID]}, payload(lot="abc/100"),
         ValueError, LOT_PARSE, [BALANCE]),
        ("lot with two steps", {"open_positions": [XAUUSD_ID]}, payload(lot="0.01/100/2"),
         ValueError, "too many values", [BALANCE]),
        ("zero balance step", {"open_positions": [XAUUSD_ID]}, payload(lot="0.01/0"),
         ZeroDivisionError, None, [BALANCE]),
        ("unknown symbol on open", {}, payload(symbol="GBPUSD"),
         ValueError, "No instrument found", [BALANCE, UNKNOWN_LOOKUP]),
        ("unknown symbol on close", {}, payload(symbol="GBPUSD", action="close"),
         ValueError, "No instrument found", [BALANCE, UNKNOWN_LOOKUP]),
        ("invalid isInvert resolves after the second lookup", {"open_positions": [XAUUSD_ID]},
         payload(invert="Sideways"), ValueError, "isInvert",
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, LOOKUP]),
        ("broker rejects the order", {"order_results": (order_rejection(),)},
         payload(), TLAPIOrderException, None,
         [BALANCE, LOOKUP, POSITIONS, LOOKUP, ORDER]),
        ("broker rejects the order after the position was closed",
         {"open_positions": [XAUUSD_ID], "order_results": (order_rejection(),)},
         payload(), TLAPIOrderException, None,
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, LOOKUP, ORDER]),
        ("account state without a balance field", {"balance": NO_BALANCE_FIELD},
         payload(), TypeError, "NoneType", [BALANCE]),
        ("no balance field and a malformed lot: the parse fails first",
         {"balance": NO_BALANCE_FIELD}, payload(lot="abc/100"), ValueError, LOT_PARSE, [BALANCE]),
    ],
)
def test_raising_path_call_sequence(scenario, fake_args, lines, error, match, expected):
    fake = broker(**fake_args)

    with pytest.raises(error, match=match) as raised:
        handle(fake, lines)

    assert raised.type is error, scenario
    assert fake.calls == expected, scenario


@pytest.mark.parametrize(
    ("scenario", "action", "expected"),
    [
        ("close never reads isInvert", "close", [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS]),
        ("unknown action never reads isInvert", "hold", [BALANCE]),
    ],
)
def test_invalid_invert_is_ignored_outside_open(scenario, action, expected):
    fake = broker(open_positions=[XAUUSD_ID])

    handle(fake, payload(action=action, invert="Sideways"))

    assert fake.calls == expected, scenario
