"""Exact broker call sequences and exact exception types on the raising paths
of the webhook's signal handler, and the lines ``close`` never reads.

The success-path pins fix the order of broker calls, but a restructure could
still change which calls happen before a failure: reading the balance on
``close`` again, or looking the symbol up before the balance on ``open``. The
type is compared exactly, because ``pytest.raises`` alone would also accept a
new subclass of the client's exception.

Input errors no longer raise: step 3 refuses them before any broker call, and
step 3b refuses a missing balance, an unknown symbol and an unusable quantity
before any close request (``test_rejected_signals``), and step 6i reports an
order the broker rejects (ADR 0021). What still raises is a broker call that
got no answer, an order request among them, since then nobody knows whether
the order was placed.
"""

import pytest
from tradelocker.exceptions import TLAPIException

from tests.characterization.harness import (
    BALANCE,
    CLOSE,
    LOOKUP,
    ORDER,
    POSITIONS,
    XAUUSD_ID,
    broker,
    handle,
    payload,
)

NO_ANSWER = {("create_order", 1): TLAPIException("Request failed: read timed out")}


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "expected"),
    [
        ("order request gets no answer", {"failures": NO_ANSWER},
         payload(), TLAPIException,
         [BALANCE, LOOKUP, POSITIONS, ORDER]),
        ("order request gets no answer after the position was closed",
         {"open_positions": [XAUUSD_ID], "failures": NO_ANSWER},
         payload(), TLAPIException,
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
