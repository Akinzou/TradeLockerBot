"""``ExecuteSignal`` against in-memory ports that share one journal, so the
order of broker calls and console lines relative to each other is checked.

How the close waits for the broker is in ``test_close_loop``."""

import pytest

from tests.unit.application.in_memory import (
    CLOSE_SIGNAL, LOOKUP, NO_ROWS, PAUSE, PLACE, START, XAUUSD, execute, run, signal, use_case,
)
from tradelocker_bot.application.ports import BrokerFailure, OrderRejected
from tradelocker_bot.application.refusal import NoBalance, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import UnusableQuantity
from tradelocker_bot.domain.result import Err
from tradelocker_bot.domain.signal import CloseSignal, Side


def test_open_with_nothing_to_close_looks_up_once_then_orders():
    assert run(signal()) == [*START, NO_ROWS, PLACE, ("placed", 9001), ("unlocked",)]


def test_close_needs_no_balance_and_places_no_order():
    assert run(CLOSE_SIGNAL, rows=(1, 0)) == [
        LOOKUP, ("locked",), NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), NO_ROWS, ("unlocked",),
    ]


def test_quantity_is_sized_from_the_balance():
    assert run(signal(), balance=1234.0)[4] == ("place", XAUUSD, 0.12, Side.BUY, 1000, 500)


def test_the_signal_side_is_ordered():
    journal = run(signal(side=Side.SELL))

    assert journal[4:] == [("place", XAUUSD, 0.1, Side.SELL, 1000, 500), ("placed", 9001), ("unlocked",)]


def test_an_order_id_of_zero_is_a_placed_order():
    # Legacy took a falsy id for a failed order and placed it again; the port
    # returns an id only for an order the broker created.
    assert run(signal(), order_results=(0,))[4:] == [PLACE, ("placed", 0), ("unlocked",)]


@pytest.mark.parametrize(
    ("scenario", "sig", "balance", "refusal", "journal"),
    [
        ("no balance", signal(), None, NoBalance(), [("balance",)]),
        ("quantity rounds to zero", signal(), 10.0, UnusableQuantity(balance=10.0, quantity=0.0), [("balance",)]),
        ("unknown symbol on open", signal(symbol="GBPUSD"), 1000.0, UnknownSymbol("GBPUSD"),
         [("balance",), ("instrument_id", "GBPUSD")]),
        ("unknown symbol on close", CloseSignal(symbol="GBPUSD"), 1000.0, UnknownSymbol("GBPUSD"),
         [("instrument_id", "GBPUSD")]),
    ],
)
def test_a_refusal_is_returned_before_locked_and_any_close(scenario, sig, balance, refusal, journal):
    assert execute(sig, balance=balance, rows=(1, 0)) == (Err(refusal), journal), scenario


CLOSE = [("request_close", XAUUSD), ("closing", "XAUUSD")]


@pytest.mark.parametrize(
    ("scenario", "failing_call", "sig", "rows", "order_results", "expected"),
    [
        ("balance", ("balance", 1), signal(), (0,), (9001,), [("balance",)]),
        ("lookup", ("instrument_id", 1), signal(), (0,), (9001,), [("balance",), LOOKUP]),
        ("position count", ("position_count", 1), signal(), (0,), (9001,), [*START, NO_ROWS]),
        ("first close request: no closing line", ("request_close", 1), signal(), (2, 0), (9001,),
         [*START, NO_ROWS, ("request_close", XAUUSD)]),
        ("second close request", ("request_close", 2), signal(), (2, 0), (9001,),
         [*START, NO_ROWS, *CLOSE, ("request_close", XAUUSD)]),
        ("recount", ("position_count", 2), signal(), (1, 0), (9001,), [*START, NO_ROWS, *CLOSE, NO_ROWS]),
        ("order", ("place", 1), signal(), (0,), (9001,), [*START, NO_ROWS, PLACE]),
        ("lookup on close", ("instrument_id", 1), CLOSE_SIGNAL, (0,), (9001,), [LOOKUP]),
        ("position count on close", ("position_count", 1), CLOSE_SIGNAL, (0,), (9001,),
         [LOOKUP, ("locked",), NO_ROWS]),
        ("close request on close", ("request_close", 1), CLOSE_SIGNAL, (1, 0), (9001,),
         [LOOKUP, ("locked",), NO_ROWS, ("request_close", XAUUSD)]),
        ("recount on close", ("position_count", 2), CLOSE_SIGNAL, (1, 0), (9001,),
         [LOOKUP, ("locked",), NO_ROWS, *CLOSE, NO_ROWS]),
        # No upper limit on the wait, but a count that gets no answer still
        # ends it at once (ADR 0022).
        ("count after a pause", ("position_count", 3), CLOSE_SIGNAL, (1, 1, 0), (9001,),
         [LOOKUP, ("locked",), NO_ROWS, *CLOSE, NO_ROWS, PAUSE, NO_ROWS]),
        ("close requested again", ("request_close", 2), CLOSE_SIGNAL, (1,) * 12 + (0,), (9001,),
         [LOOKUP, ("locked",), NO_ROWS, *CLOSE, NO_ROWS, *[PAUSE, NO_ROWS] * 10, ("request_close", XAUUSD)]),
    ],
)
def test_a_broker_failure_is_returned_at_once_without_unlocked(
    scenario, failing_call, sig, rows, order_results, expected
):
    cause = RuntimeError(scenario)
    journal = []

    result = use_case(journal, rows=rows, order_results=order_results, failures={failing_call: cause}).execute(sig)

    assert result == Err(BrokerFailure(cause)), scenario
    assert result.error.cause is cause, scenario
    assert journal == expected, scenario


@pytest.mark.parametrize(
    ("scenario", "rows", "closed", "left_open"),
    [
        ("nothing to close", (0, 0), [], 0),
        ("after the close", (1, 0, 0), [*CLOSE, NO_ROWS], 0),
        # A resent order that filled before the rejection, or one opened by
        # hand: the line must not say the account is flat.
        ("a position appeared meanwhile", (0, 1), [], 1),
    ],
)
def test_a_rejected_order_is_placed_once_and_reported_with_a_fresh_count(scenario, rows, closed, left_open):
    # Placed once: the broker answered no, so the same order again would get
    # the same answer, and a loop until it does not would hold the lock.
    rejection = OrderRejected("Not enough margin")

    result, journal = execute(signal(), rows=rows, order_results=(rejection, 9001))

    assert result == Err(rejection), scenario
    assert journal == [
        *START, NO_ROWS, *closed, PLACE,
        NO_ROWS, ("rejected", "XAUUSD", Side.BUY, "Not enough margin", left_open), ("unlocked",),
    ], scenario


def test_a_rejection_whose_recount_fails_is_reported_and_returns_the_failure():
    # The line still says what was refused, and that the state is unknown;
    # the failed count then raises like any call that got no answer.
    cause = RuntimeError("positions unavailable")
    journal = []

    result = use_case(journal, rows=(0, 0), order_results=(OrderRejected(None),),
                      failures={("position_count", 2): cause}).execute(signal())

    assert result == Err(BrokerFailure(cause))
    assert journal == [*START, NO_ROWS, PLACE, NO_ROWS, ("rejected", "XAUUSD", Side.BUY, None, None)]
