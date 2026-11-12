"""Exact broker call sequences, lock coverage and console lines, as ADR 0001's
equivalence rule demands.

Relative-order assertions elsewhere would let a restructuring drop a lookup,
merge per-row close requests, split the critical section or drop an operator
line unnoticed.
"""

import pytest
from tradelocker.exceptions import TLAPIException

from tests.characterization.harness import (
    BALANCE,
    CLOSE,
    EURUSD_ID,
    LOCK_ACQUIRED,
    LOCK_RELEASED,
    LOOKUP,
    ORDER,
    PAUSE,
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
        # Counted again at once, then once a second, and asked again only
        # every 10 seconds (ADR 0022).
        ("close requested again after 10 seconds", [XAUUSD_ID], 2, "close",
         [LOOKUP, POSITIONS, CLOSE, POSITIONS, *[PAUSE, POSITIONS] * 10, CLOSE, POSITIONS]),
        ("one close request per position row", [XAUUSD_ID, XAUUSD_ID], 1, "close",
         [LOOKUP, POSITIONS, CLOSE, CLOSE, POSITIONS]),
    ],
)
def test_exact_broker_call_sequence(scenario, open_positions, close_requests_to_fill, action, expected):
    fake = broker(open_positions=open_positions, close_requests_to_fill=close_requests_to_fill)

    handle(fake, payload(action=action))

    assert fake.calls == expected, scenario


@pytest.mark.parametrize(
    ("scenario", "open_positions", "expected"),
    [
        ("nothing to close", [], [BALANCE, LOOKUP, POSITIONS, ORDER, POSITIONS]),
        ("after the close", [XAUUSD_ID], [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS, ORDER, POSITIONS]),
    ],
)
@pytest.mark.parametrize("answer", [order_rejection(), None], ids=["rejected", "no id"])
def test_an_order_is_placed_once_even_when_the_broker_creates_none(scenario, open_positions, answer, expected):
    # Before step 6i an answer without an id was ordered again, with no pause
    # and no end; the client gives one only on its netting path, which the bot
    # does not use. A rejection raised before. The positions are counted
    # again for the operator line (ADR 0021).
    fake = broker(open_positions=open_positions, order_results=(answer, 9001))

    handle(fake, payload())

    assert fake.calls == expected, scenario
    assert fake.open_positions == [], scenario


@pytest.mark.parametrize(
    ("action", "fake_args"),
    [
        ("open", {}),
        ("close", {}),
        ("open", {"order_results": (order_rejection(),)}),
    ],
)
def test_whole_handling_is_one_critical_section(action, fake_args):
    fake = broker(open_positions=[XAUUSD_ID], **fake_args)
    lock = RecordingLock(fake)

    handle(fake, payload(action=action), lock)

    assert lock.events == [("acquire", 0), ("release", len(fake.calls))]
    assert not lock.locked()


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error"),
    [
        ("the order request gets no answer",
         {"failures": {("create_order", 1): TLAPIException("Request failed: read timed out")}},
         payload(), TLAPIException),
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
FLAT = "no XAUUSD position is open"
STILL_OPEN = ("Still closing: the broker lists 1 open XAUUSD position 60 seconds after the first close request; "
              "later signals wait until it closes, check it in TradeLocker")
CLOSED = "Closed after 70 seconds: the broker lists no open XAUUSD position"
REJECTED = f"Order rejected: the broker refused to buy XAUUSD ('Not enough margin'); {FLAT}"


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "error", "expected"),
    [
        ("open, nothing to close", {}, payload(), None,
         [*LOCKED, PLACED, *UNLOCKED]),
        ("open replaces two position rows", {"open_positions": [XAUUSD_ID, XAUUSD_ID]}, payload(), None,
         [*LOCKED, CLOSING, CLOSING, PLACED, *UNLOCKED]),
        ("order answered without an id", {"order_results": (None, 9001)}, payload(), None,
         [*LOCKED, f"Order rejected: the broker refused to buy XAUUSD (no reason given); {FLAT}", *UNLOCKED]),
        ("inverted order answered without an id", {"order_results": (None, 9001)}, payload(invert="Invert"), None,
         [*LOCKED, f"Order rejected: the broker refused to sell XAUUSD (no reason given); {FLAT}", *UNLOCKED]),
        ("close requested again every 10 seconds", {"open_positions": [XAUUSD_ID], "close_requests_to_fill": 3},
         payload(action="close"), None,
         [*LOCKED, CLOSING, CLOSING, CLOSING, *UNLOCKED]),
        # One line a minute after the first request, then none however long
        # the close takes, until one that it ended (ADR 0022).
        ("still open a minute after the first request",
         {"open_positions": [XAUUSD_ID], "close_requests_to_fill": 8},
         payload(action="close"), None,
         [*LOCKED, *[CLOSING] * 6, STILL_OPEN, CLOSING, CLOSING, CLOSED, *UNLOCKED]),
        # The order comes after the line, still inside the lock.
        ("open waits a minute for the close",
         {"open_positions": [XAUUSD_ID], "close_requests_to_fill": 8},
         payload(), None,
         [*LOCKED, *[CLOSING] * 6, STILL_OPEN, CLOSING, CLOSING, CLOSED, PLACED, *UNLOCKED]),
        # One line in place of the traceback, inside Locked and Unlocked, since
        # the handling ends there (ADR 0021).
        ("broker rejects the order after the close",
         {"open_positions": [XAUUSD_ID],
          "order_results": (order_rejection(),)},
         payload(), None,
         [*LOCKED, CLOSING, REJECTED, *UNLOCKED]),
        ("broker rejects the order, nothing to close",
         {"order_results": (order_rejection(),)},
         payload(), None,
         [*LOCKED, REJECTED, *UNLOCKED]),
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
