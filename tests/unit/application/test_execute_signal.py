"""``ExecuteSignal`` against in-memory ports that share one journal, so the
order of broker calls and console lines relative to each other is checked."""

from collections import Counter

import pytest

from tradelocker_bot.application.execute_signal import ExecuteSignal
from tradelocker_bot.application.ports import BrokerFailure
from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.result import Err, Ok
from tradelocker_bot.domain.signal import CloseSignal, OpenSignal, Side

XAUUSD = 101


class FakeBroker:
    """Answers with ``Ok``; ``failures`` maps ``(journal entry, nth call)``,
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
        return Err(BrokerFailure(failure)) if failure is not None else Ok(value)

    def account_balance(self):
        return self._answer(("balance",), self._balance)

    def instrument_id(self, symbol):
        return self._answer(("instrument_id", symbol), XAUUSD)

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

    def order_retry(self, side):
        self._journal.append(("retry", side))

    def order_placed(self, order_id):
        self._journal.append(("placed", order_id))

    def unlocked(self):
        self._journal.append(("unlocked",))


def signal(side=Side.BUY, base_lot=0.01):
    return OpenSignal(symbol="XAUUSD", side=side, sizing=LotSizing(base_lot=base_lot, balance_step=100.0),
                      take_profit=500, stop_loss=1000)


CLOSE_SIGNAL = CloseSignal(symbol="XAUUSD")


def run(sig, **broker_args):
    journal = []
    assert ExecuteSignal(FakeBroker(journal, **broker_args), FakeConsole(journal)).execute(sig) == Ok(None)
    return journal


def run_raising(sig, error, **broker_args):
    journal = []
    with pytest.raises(error) as raised:
        ExecuteSignal(FakeBroker(journal, **broker_args), FakeConsole(journal)).execute(sig)
    assert raised.type is error
    return journal


START = [("balance",), ("locked",)]
LOOKUP = ("instrument_id", "XAUUSD")
NO_ROWS = ("position_count", XAUUSD)
PLACE = ("place", XAUUSD, 0.1, Side.BUY, 1000, 500)


def test_open_with_nothing_to_close_looks_up_twice_then_orders():
    assert run(signal()) == [*START, LOOKUP, NO_ROWS, LOOKUP, PLACE, ("placed", 9001), ("unlocked",)]


def test_open_requests_one_close_per_row_and_polls_until_none_are_left():
    assert run(signal(), rows=(2, 1, 0)) == [
        *START, LOOKUP,
        NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), ("request_close", XAUUSD), ("closing", "XAUUSD"),
        NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"),
        NO_ROWS,
        LOOKUP, PLACE, ("placed", 9001), ("unlocked",),
    ]


def test_close_needs_no_balance_and_makes_no_second_lookup_or_order():
    assert run(CLOSE_SIGNAL, rows=(1, 0)) == [
        ("locked",), LOOKUP, NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), NO_ROWS, ("unlocked",),
    ]


def test_quantity_is_sized_from_the_balance():
    assert run(signal(), balance=1234.0)[5] == ("place", XAUUSD, 0.12, Side.BUY, 1000, 500)


def test_the_signal_side_is_ordered_and_named_in_the_retry_line():
    journal = run(signal(side=Side.SELL), order_results=(None, 0, 9001))

    assert journal[4:] == [
        LOOKUP,
        ("place", XAUUSD, 0.1, Side.SELL, 1000, 500), ("retry", Side.SELL),
        ("place", XAUUSD, 0.1, Side.SELL, 1000, 500), ("retry", Side.SELL),
        ("place", XAUUSD, 0.1, Side.SELL, 1000, 500), ("placed", 9001),
        ("unlocked",),
    ]


def test_balance_reaches_the_lot_sizing_uncoerced():
    assert run_raising(signal(), TypeError, balance=None) == [("balance",)]


CLOSE = [("request_close", XAUUSD), ("closing", "XAUUSD")]


@pytest.mark.parametrize(
    ("scenario", "failing_call", "sig", "rows", "order_results", "expected"),
    [
        ("balance", ("balance", 1), signal(), (0,), (9001,), [("balance",)]),
        ("first lookup", ("instrument_id", 1), signal(), (0,), (9001,), [*START, LOOKUP]),
        ("position count", ("position_count", 1), signal(), (0,), (9001,), [*START, LOOKUP, NO_ROWS]),
        ("first close request: no closing line", ("request_close", 1), signal(), (2, 0), (9001,),
         [*START, LOOKUP, NO_ROWS, ("request_close", XAUUSD)]),
        ("second close request", ("request_close", 2), signal(), (2, 0), (9001,),
         [*START, LOOKUP, NO_ROWS, *CLOSE, ("request_close", XAUUSD)]),
        ("recount", ("position_count", 2), signal(), (1, 0), (9001,), [*START, LOOKUP, NO_ROWS, *CLOSE, NO_ROWS]),
        ("second lookup", ("instrument_id", 2), signal(), (0,), (9001,), [*START, LOOKUP, NO_ROWS, LOOKUP]),
        ("order", ("place", 1), signal(), (0,), (9001,), [*START, LOOKUP, NO_ROWS, LOOKUP, PLACE]),
        ("order placed again", ("place", 2), signal(), (0,), (None, 9001),
         [*START, LOOKUP, NO_ROWS, LOOKUP, PLACE, ("retry", Side.BUY), PLACE]),
        ("lookup on close", ("instrument_id", 1), CLOSE_SIGNAL, (0,), (9001,), [("locked",), LOOKUP]),
        ("position count on close", ("position_count", 1), CLOSE_SIGNAL, (0,), (9001,),
         [("locked",), LOOKUP, NO_ROWS]),
        ("close request on close", ("request_close", 1), CLOSE_SIGNAL, (1, 0), (9001,),
         [("locked",), LOOKUP, NO_ROWS, ("request_close", XAUUSD)]),
        ("recount on close", ("position_count", 2), CLOSE_SIGNAL, (1, 0), (9001,),
         [("locked",), LOOKUP, NO_ROWS, *CLOSE, NO_ROWS]),
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
