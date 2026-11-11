"""Exact broker call sequences and exact exception types on the raising paths
of ``handle_position_normal``, and the lines ``close`` never reads.

The success-path pins fix the order of broker calls, but a restructure could
still change which calls happen before a failure: reading the balance on
``close`` again, or looking the symbol up before the balance on ``open``. The
type is compared exactly, because ``pytest.raises`` alone would also accept a
new subclass of the client's exception.

Where two raise sites share a type, ``match`` names the site that must fail.
Input errors no longer raise: step 3 refuses them before any broker call
(``test_rejected_signals``). What still raises needs the broker's answer, and
the unknown symbol and the missing balance are refused in step 3b.
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


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "match", "expected"),
    [
        ("unknown symbol on open", {}, payload(symbol="GBPUSD"),
         ValueError, "No instrument found", [BALANCE, UNKNOWN_LOOKUP]),
        ("unknown symbol on close: no balance read", {}, payload(symbol="GBPUSD", action="close"),
         ValueError, "No instrument found", [UNKNOWN_LOOKUP]),
        ("broker rejects the order", {"order_results": (order_rejection(),)},
         payload(), TLAPIOrderException, None,
         [BALANCE, LOOKUP, POSITIONS, LOOKUP, ORDER]),
        ("broker rejects the order after the position was closed",
         {"open_positions": [XAUUSD_ID], "order_results": (order_rejection(),)},
         payload(), TLAPIOrderException, None,
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, LOOKUP, ORDER]),
        ("account state without a balance field", {"balance": NO_BALANCE_FIELD},
         payload(), TypeError, "NoneType", [BALANCE]),
    ],
)
def test_raising_path_call_sequence(scenario, fake_args, lines, error, match, expected):
    fake = broker(**fake_args)

    with pytest.raises(error, match=match) as raised:
        handle(fake, lines)

    assert raised.type is error, scenario
    assert fake.calls == expected, scenario


@pytest.mark.parametrize(
    "lines",
    [
        payload(action="close", invert="Sideways"),
        payload(action="close", direction="long", lot="x", tp="", sl="?"),
        payload(action="close")[:6],
    ],
)
def test_close_reads_only_the_symbol_and_the_action(lines):
    fake = broker(open_positions=[XAUUSD_ID])

    handle(fake, lines)

    assert fake.calls == [LOOKUP, POSITIONS, CLOSE, POSITIONS]
