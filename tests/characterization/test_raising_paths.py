"""Exact broker call sequences and exception types on every raising path, and
for inputs whose problems legacy code never reaches.

The success-path pins fix the order of broker calls, but a restructure could
still move a validation earlier or later on a failing signal: resolving the
trade side before the second instrument lookup, or for actions that never
use it, or coercing the balance before the lot is parsed. Each of those
changes which broker calls happen before the failure, or whether it fails.
"""

import pytest
from tradelocker.exceptions import TLAPIOrderException

from tests.characterization.harness import DEFAULT_ORDER, XAUUSD_ID, broker, handle, payload

BALANCE = ("get_account_state",)
LOOKUP = ("get_instrument_id_from_symbol_name", "XAUUSD")
POSITIONS = ("get_all_positions",)
CLOSE = ("close_all_positions", XAUUSD_ID)
ORDER = ("create_order", XAUUSD_ID, DEFAULT_ORDER)


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "expected"),
    [
        ("non-numeric take profit", {}, payload(tp="5x"), ValueError, []),
        ("non-numeric stop loss", {}, payload(sl="1e3"), ValueError, []),
        ("truncated payload", {}, payload()[:6], IndexError, []),
        ("malformed lot", {}, payload(lot="abc/100"), ValueError, [BALANCE]),
        ("zero balance step", {}, payload(lot="0.01/0"), ZeroDivisionError, [BALANCE]),
        ("invalid isInvert resolves after the second lookup", {"open_positions": [XAUUSD_ID]},
         payload(invert="Sideways"), ValueError,
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, LOOKUP]),
        ("broker rejects the order",
         {"order_results": (TLAPIOrderException({}, {"errmsg": "Not enough margin"}),)},
         payload(), TLAPIOrderException,
         [BALANCE, LOOKUP, POSITIONS, LOOKUP, ORDER]),
        ("missing balance with a valid lot", {"balance": None}, payload(), TypeError, [BALANCE]),
        ("missing balance with a malformed lot: the parse fails first", {"balance": None},
         payload(lot="abc/100"), ValueError, [BALANCE]),
    ],
)
def test_raising_path_call_sequence(scenario, fake_args, lines, error, expected):
    fake = broker(**fake_args)

    with pytest.raises(error):
        handle(fake, lines)

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
