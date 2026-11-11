"""Exact broker call sequences, lock coverage and console lines, as ADR 0001's
equivalence rule demands.

Relative-order assertions elsewhere would let a restructuring drop a lookup,
merge per-row close requests, split the critical section or drop an operator
line unnoticed.
"""

import pytest
from tradelocker.exceptions import TLAPIOrderException

from tests.characterization.harness import (
    BALANCE,
    CLOSE,
    EURUSD_ID,
    LOCK_ACQUIRED,
    LOCK_RELEASED,
    LOOKUP,
    ORDER,
    POSITIONS,
    XAUUSD_ID,
    RecordingLock,
    broker,
    console_lines,
    handle,
    order_rejection,
    payload,
)


@pytest.mark.parametrize(
    ("scenario", "open_positions", "close_requests_to_fill", "action", "expected"),
    [
        ("open, nothing to close", [], 1, "open",
         [BALANCE, LOOKUP, POSITIONS, ORDER]),
        ("open replaces existing position", [XAUUSD_ID], 1, "open",
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, ORDER]),
        ("open ignores other instruments", [EURUSD_ID], 1, "open",
         [BALANCE, LOOKUP, POSITIONS, ORDER]),
        # close sizes nothing, so it no longer reads the balance (ADR 0008).
        ("close", [XAUUSD_ID], 1, "close",
         [LOOKUP, POSITIONS, CLOSE, POSITIONS]),
        ("close re-requested until filled", [XAUUSD_ID], 3, "close",
         [LOOKUP, POSITIONS, CLOSE, POSITIONS, CLOSE, POSITIONS, CLOSE, POSITIONS]),
        ("one close request per position row", [XAUUSD_ID, XAUUSD_ID], 1, "close",
         [LOOKUP, POSITIONS, CLOSE, CLOSE, POSITIONS]),
    ],
)
def test_exact_broker_call_sequence(scenario, open_positions, close_requests_to_fill, action, expected):
    fake = broker(open_positions=open_positions, close_requests_to_fill=close_requests_to_fill)

    handle(fake, payload(action=action))

    assert fake.calls == expected, scenario


def test_order_without_an_id_is_placed_again():
    # The client returns None only on its netting path, which the bot does not
    # use, so this loop is unreachable in production. It is pinned so a
    # restructuring cannot drop it silently; removing it is a declared change.
    fake = broker(order_results=(None, 9001))

    handle(fake, payload())

    assert fake.calls == [BALANCE, LOOKUP, POSITIONS, ORDER, ORDER]


@pytest.mark.parametrize("action", ["open", "close"])
def test_whole_handling_is_one_critical_section(action):
    fake = broker(open_positions=[XAUUSD_ID])
    lock = RecordingLock(fake)

    handle(fake, payload(action=action), lock)

    assert lock.events == [("acquire", 0), ("release", len(fake.calls))]
    assert not lock.locked()


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error"),
    [
        ("broker rejects the order",
         {"order_results": (order_rejection(),)},
         payload(), TLAPIOrderException),
        ("broker fails the lookup", {"failures": {("get_all_instruments", 1): ValueError("bad body")}},
         payload(), ValueError),
    ],
)
def test_lock_is_released_when_handling_raises(scenario, fake_args, lines, error):
    fake = broker(open_positions=[XAUUSD_ID], **fake_args)
    lock = RecordingLock(fake)

    with pytest.raises(error):
        handle(fake, lines, lock)

    assert lock.events == [("acquire", 0), ("release", len(fake.calls))], scenario
    assert not lock.locked(), scenario


LOCKED = [LOCK_ACQUIRED, "Normal: Locked"]
UNLOCKED = ["Normal: Unlocked", LOCK_RELEASED]
CLOSING = "Closing: XAUUSD"
PLACED = "Order placed successfully, order ID: 9001"


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "expected"),
    [
        ("open, nothing to close", {}, payload(), None,
         [*LOCKED, PLACED, *UNLOCKED]),
        ("open replaces two position rows", {"open_positions": [XAUUSD_ID, XAUUSD_ID]}, payload(), None,
         [*LOCKED, CLOSING, CLOSING, PLACED, *UNLOCKED]),
        ("order placed again", {"order_results": (None, 9001)}, payload(), None,
         [*LOCKED, "Buy order was not successful, trying again...", PLACED, *UNLOCKED]),
        ("inverted order placed again", {"order_results": (None, 9001)}, payload(invert="Invert"), None,
         [*LOCKED, "Sell order was not successful, trying again...", PLACED, *UNLOCKED]),
        ("close re-requested until filled", {"open_positions": [XAUUSD_ID], "close_requests_to_fill": 3},
         payload(action="close"), None,
         [*LOCKED, CLOSING, CLOSING, CLOSING, *UNLOCKED]),
        ("broker rejects the order",
         {"open_positions": [XAUUSD_ID],
          "order_results": (order_rejection(),)},
         payload(), TLAPIOrderException,
         [*LOCKED, CLOSING, LOCK_RELEASED]),
    ],
)
def test_operator_console_lines(capsys, scenario, fake_args, lines, error, expected):
    fake = broker(**fake_args)

    if error:
        with pytest.raises(error):
            handle(fake, lines, RecordingLock(fake))
    else:
        handle(fake, lines, RecordingLock(fake))

    assert console_lines(capsys) == expected, scenario
