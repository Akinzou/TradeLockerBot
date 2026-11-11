"""A failing broker call, at every call the handler makes: which calls happened
before it, which operator lines were written, that the critical section is
released, and that the very exception the client raised leaves the handler.

The raising-path table already pins an unknown symbol and a rejected order;
the balance read, the position list, the close request and the recount had no
pin. Identity rather than type is asserted, because a restructure that catches
the client's exception and raises a new one of the same type would pass a type
check and still lose the original's attributes and traceback.

The handler is called directly, so these pins end at its caller. Whether the
webhook thread still receives the exception belongs to the inbound adapter
(roadmap step 5).
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
        ("first instrument lookup", ("get_instrument_id_from_symbol_name", 1), {}, payload(),
         [BALANCE, LOOKUP], [*LOCKED, LOCK_RELEASED]),
        ("position list", ("get_all_positions", 1), {}, payload(),
         [BALANCE, LOOKUP, POSITIONS], [*LOCKED, LOCK_RELEASED]),
        ("first close request: no closing line", ("close_all_positions", 1), TWO_ROWS, payload(),
         [BALANCE, LOOKUP, POSITIONS, CLOSE], [*LOCKED, LOCK_RELEASED]),
        ("second close request in one poll", ("close_all_positions", 2), TWO_ROWS, payload(),
         [BALANCE, LOOKUP, POSITIONS, CLOSE, CLOSE], [*LOCKED, CLOSING, LOCK_RELEASED]),
        ("recount after closing", ("get_all_positions", 2), ONE_ROW, payload(),
         [BALANCE, LOOKUP, POSITIONS, CLOSE, POSITIONS], [*LOCKED, CLOSING, LOCK_RELEASED]),
        ("second instrument lookup", ("get_instrument_id_from_symbol_name", 2), {}, payload(),
         [BALANCE, LOOKUP, POSITIONS, LOOKUP], [*LOCKED, LOCK_RELEASED]),
        ("order", ("create_order", 1), {}, payload(),
         [BALANCE, LOOKUP, POSITIONS, LOOKUP, ORDER], [*LOCKED, LOCK_RELEASED]),
        ("order placed again", ("create_order", 2), {"order_results": (None,)}, payload(),
         [BALANCE, LOOKUP, POSITIONS, LOOKUP, ORDER, ORDER], [*LOCKED, RETRY, LOCK_RELEASED]),
        ("lookup on close", ("get_instrument_id_from_symbol_name", 1), {}, payload(action="close"),
         [LOOKUP], [*LOCKED, LOCK_RELEASED]),
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
