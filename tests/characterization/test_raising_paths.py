"""Exact broker call sequences and exact exception types on the raising paths
of ``handle_position_normal``, and the lines ``close`` never reads.

The success-path pins fix the order of broker calls, but a restructure could
still change which calls happen before a failure: reading the balance on
``close`` again, or looking the symbol up before the balance on ``open``. The
type is compared exactly, because ``pytest.raises`` alone would also accept a
new subclass of the client's exception.

Input errors no longer raise: step 3 refuses them before any broker call, and
step 3b refuses a missing balance, an unknown symbol and an unusable quantity
before any close request (``test_rejected_signals``). What still raises is a
broker failure; reporting it instead is roadmap step 6.
"""

import pytest
from tradelocker.exceptions import TLAPIOrderException

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


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "expected"),
    [
        ("broker rejects the order", {"order_results": (order_rejection(),)},
         payload(), TLAPIOrderException,
         [BALANCE, LOOKUP, POSITIONS, ORDER]),
        ("broker rejects the order after the position was closed",
         {"open_positions": [XAUUSD_ID], "order_results": (order_rejection(),)},
         payload(), TLAPIOrderException,
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, ORDER]),
    ],
)
def test_raising_path_call_sequence(scenario, fake_args, lines, error, expected):
    fake = broker(**fake_args)

    with pytest.raises(error) as raised:
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
