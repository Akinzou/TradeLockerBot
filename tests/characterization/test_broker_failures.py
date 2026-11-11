"""A failing broker call, at every call the handler makes: which calls happened
before it, which operator lines were written, that the critical section is
released, and that the very exception the client raised leaves the handler.

The raising-path table already pins a rejected order; the balance read, the
instrument lookup, the position list, the close request and the recount had no
other pin. Identity rather than type is asserted, because a restructure that catches
the client's exception and raises a new one of the same type would pass a type
check and still lose the original's attributes and traceback.

The handler is called directly, so these pins end at its caller. That the
webhook thread receives the exception is pinned in ``test_webhook_route.py``.
"""

import pytest
from tradelocker.exceptions import TLAPIException

from tests.characterization.harness import (
    BALANCE,
    CLOSE,
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
    payload,
)

LOCKED = [LOCK_ACQUIRED, "Normal: Locked"]
CLOSING = "Closing: XAUUSD"
RETRY = "Buy order was not successful, trying again..."
TWO_ROWS = {"open_positions": [XAUUSD_ID, XAUUSD_ID]}
ONE_ROW = {"open_positions": [XAUUSD_ID]}


@pytest.mark.parametrize(
    ("scenario", "failing_call", "fake_args", "lines", "calls", "console"),
    [
        ("balance read", ("get_account_state", 1), {}, payload(),
         [BALANCE], [LOCK_ACQUIRED, LOCK_RELEASED]),
        # The lookup now comes before the "Normal: Locked" line (ADR 0009).
        ("instrument lookup", ("get_all_instruments", 1), {}, payload(),
         [BALANCE, LOOKUP], [LOCK_ACQUIRED, LOCK_RELEASED]),
        ("position list", ("get_all_positions", 1), {}, payload(),
         [BALANCE, LOOKUP, POSITIONS], [*LOCKED, LOCK_RELEASED]),
        ("first close request: no closing line", ("close_all_positions", 1), TWO_ROWS, payload(),
         [BALANCE, LOOKUP, POSITIONS, CLOSE], [*LOCKED, LOCK_RELEASED]),
        ("second close request in one poll", ("close_all_positions", 2), TWO_ROWS, payload(),
         [BALANCE, LOOKUP, POSITIONS, CLOSE, CLOSE], [*LOCKED, CLOSING, LOCK_RELEASED]),
        ("recount after closing", ("get_all_positions", 2), ONE_ROW, payload(),
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS], [*LOCKED, CLOSING, LOCK_RELEASED]),
        ("order", ("create_order", 1), {}, payload(),
         [BALANCE, LOOKUP, POSITIONS, ORDER], [*LOCKED, LOCK_RELEASED]),
        ("order placed again", ("create_order", 2), {"order_results": (None,)}, payload(),
         [BALANCE, LOOKUP, POSITIONS, ORDER, ORDER], [*LOCKED, RETRY, LOCK_RELEASED]),
        ("lookup on close", ("get_all_instruments", 1), {}, payload(action="close"),
         [LOOKUP], [LOCK_ACQUIRED, LOCK_RELEASED]),
        ("position list on close", ("get_all_positions", 1), {}, payload(action="close"),
         [LOOKUP, POSITIONS], [*LOCKED, LOCK_RELEASED]),
        ("close request on close", ("close_all_positions", 1), ONE_ROW, payload(action="close"),
         [LOOKUP, POSITIONS, CLOSE], [*LOCKED, LOCK_RELEASED]),
        ("recount on close", ("get_all_positions", 2), ONE_ROW, payload(action="close"),
         [LOOKUP, POSITIONS, CLOSE, POSITIONS], [*LOCKED, CLOSING, LOCK_RELEASED]),
    ],
)
def test_broker_failure_propagates_as_raised(capsys, scenario, failing_call, fake_args, lines, calls, console):
    failure = TLAPIException(f"{scenario} failed")
    fake = broker(failures={failing_call: failure}, **fake_args)
    lock = RecordingLock(fake)

    with pytest.raises(TLAPIException) as raised:
        handle(fake, lines, lock)

    assert raised.value is failure, scenario
    assert fake.calls == calls, scenario
    assert lock.events == [("acquire", 0), ("release", len(calls))], scenario
    assert console_lines(capsys) == console, scenario


@pytest.mark.parametrize(
    "failure",
    [
        # The client's own bare ValueErrors for an empty answer and for one
        # that is not JSON (`_get_response_json`), next to its unknown-symbol
        # error: the same type, only the message differs.
        ValueError("Empty response received from the API for https://broker/instruments"),
        ValueError("Failed to decode JSON response from https://broker/instruments. "
                   "Received response:\n'<html>'\nExpecting value: line 1 column 1 (char 0)"),
        ValueError("No instrument found with symbol_name='XAUUSD'"),
    ],
)
def test_a_failed_lookup_is_never_mistaken_for_an_unknown_symbol(capsys, failure):
    # An outage reported as "unknown symbol" would hide it behind a calm
    # operator line (ADR 0009), so the lookup decides from the instrument
    # list, never from the type or text of an exception.
    fake = broker(failures={("get_all_instruments", 1): failure})

    with pytest.raises(ValueError) as raised:
        handle(fake, payload())

    assert raised.value is failure
    assert console_lines(capsys) == []
