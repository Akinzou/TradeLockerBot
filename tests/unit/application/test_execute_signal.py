"""``ExecuteSignal`` against in-memory ports that share one journal, so the
order of broker calls and console lines relative to each other is checked."""

from collections import Counter

import pytest

from tradelocker_bot.application.execute_signal import ExecuteSignal
from tradelocker_bot.application.ports import BrokerFailure, OrderRejected
from tradelocker_bot.application.refusal import NoBalance, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import LotSizing, UnusableQuantity
from tradelocker_bot.domain.result import Err, Ok
from tradelocker_bot.domain.signal import CloseSignal, OpenSignal, Side

XAUUSD = 101


class FakeBroker:
    """Answers with ``Ok``, or with ``Err`` for an ``OrderRejected`` among
    ``order_results``; ``failures`` maps ``(journal entry, nth call)``,
    counted from 1, to an exception whose ``BrokerFailure`` that call returns
    instead. Like ``FakeTradeLocker``, it refuses a key it would never reach."""

    CALLS = frozenset({"balance", "instrument_id", "position_count", "request_close", "place"})

    def __init__(self, journal, balance=1000.0, rows=(0,), order_results=(9001,), failures=None):
        self._journal = journal
        self._balance = balance
        self._rows = list(rows)
        self._order_results = list(order_results)
        self._failures = dict(failures or {})
        assert all(call in self.CALLS and nth >= 1 for call, nth in self._failures), self._failures
        self._counts = Counter()

    def _answer(self, entry, value):
        self._journal.append(entry)
        self._counts[entry[0]] += 1
        failure = self._failures.get((entry[0], self._counts[entry[0]]))
        if failure is not None:
            return Err(BrokerFailure(failure))
        return Err(value) if isinstance(value, OrderRejected) else Ok(value)

    def account_balance(self):
        return self._answer(("balance",), self._balance)

    def instrument_id(self, symbol):
        return self._answer(("instrument_id", symbol), XAUUSD if symbol == "XAUUSD" else None)

    def open_position_count(self, instrument_id):
        return self._answer(("position_count", instrument_id), self._rows.pop(0))

    def request_close(self, instrument_id):
        return self._answer(("request_close", instrument_id), None)

    def place_market_order(self, instrument_id, quantity, side, stop_loss, take_profit):
        return self._answer(("place", instrument_id, quantity, side, stop_loss, take_profit),
                            self._order_results.pop(0))


class FakeConsole:
    def __init__(self, journal):
        self._journal = journal

    def locked(self):
        self._journal.append(("locked",))

    def closing(self, symbol):
        self._journal.append(("closing", symbol))

    def order_placed(self, order_id):
        self._journal.append(("placed", order_id))

    def order_rejected(self, symbol, side, reason, open_positions):
        self._journal.append(("rejected", symbol, side, reason, open_positions))

    def unlocked(self):
        self._journal.append(("unlocked",))


def signal(side=Side.BUY, base_lot=0.01, symbol="XAUUSD"):
    return OpenSignal(symbol=symbol, side=side, sizing=LotSizing(base_lot=base_lot, balance_step=100.0),
                      take_profit=500, stop_loss=1000)


CLOSE_SIGNAL = CloseSignal(symbol="XAUUSD")


def execute(sig, **broker_args):
    journal = []
    result = ExecuteSignal(FakeBroker(journal, **broker_args), FakeConsole(journal)).execute(sig)
    return result, journal


def run(sig, **broker_args):
    result, journal = execute(sig, **broker_args)
    assert result == Ok(None)
    return journal


LOOKUP = ("instrument_id", "XAUUSD")
START = [("balance",), LOOKUP, ("locked",)]
NO_ROWS = ("position_count", XAUUSD)
PLACE = ("place", XAUUSD, 0.1, Side.BUY, 1000, 500)


def test_open_with_nothing_to_close_looks_up_once_then_orders():
    assert run(signal()) == [*START, NO_ROWS, PLACE, ("placed", 9001), ("unlocked",)]


def test_open_requests_one_close_per_row_and_polls_until_none_are_left():
    assert run(signal(), rows=(2, 1, 0)) == [
        *START,
        NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), ("request_close", XAUUSD), ("closing", "XAUUSD"),
        NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"),
        NO_ROWS,
        PLACE, ("placed", 9001), ("unlocked",),
    ]


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
    ],
)
def test_a_broker_failure_is_returned_at_once_without_unlocked(
    scenario, failing_call, sig, rows, order_results, expected
):
    cause = RuntimeError(scenario)
    journal = []
    broker = FakeBroker(journal, rows=rows, order_results=order_results, failures={failing_call: cause})

    result = ExecuteSignal(broker, FakeConsole(journal)).execute(sig)

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
    broker = FakeBroker(journal, rows=(0, 0), order_results=(OrderRejected(None),),
                        failures={("position_count", 2): cause})

    result = ExecuteSignal(broker, FakeConsole(journal)).execute(signal())

    assert result == Err(BrokerFailure(cause))
    assert journal == [*START, NO_ROWS, PLACE, NO_ROWS, ("rejected", "XAUUSD", Side.BUY, None, None)]
