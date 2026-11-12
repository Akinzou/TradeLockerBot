"""In-memory ports for ``ExecuteSignal`` that share one journal, so the
order of broker calls, pauses and console lines relative to each other is
checked."""

from collections import Counter

from tests.fake_clock import FakeClock
from tradelocker_bot.application.execute_signal import ExecuteSignal
from tradelocker_bot.application.ports import BrokerFailure, OrderRejected
from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.result import Err, Ok
from tradelocker_bot.domain.signal import CloseSignal, OpenSignal, Side

XAUUSD = 101


class FakeBroker:
    """Answers with ``Ok``, or with ``Err`` for an ``OrderRejected`` among
    ``order_results``; ``failures`` maps ``(journal entry, nth call)``,
    counted from 1, to an exception whose ``BrokerFailure`` that call returns
    instead. Like ``FakeTradeLocker``, it refuses a key it would never reach."""

    CALLS = frozenset({"balance", "instrument_id", "position_count", "request_close", "place"})

    def __init__(self, journal, balance=1000.0, rows=(0,), order_results=(9001,), failures=None,
                 clock=None, seconds_per_count=0.0, seconds_per_close=0.0):
        self._journal = journal
        self._clock = clock
        self._seconds_per_count = seconds_per_count
        self._seconds_per_close = seconds_per_close
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
        # A count takes time of its own: the client waits a second before
        # every request, and retries one whose connection fails.
        if self._clock is not None:
            self._clock.advance(self._seconds_per_count)
        return self._answer(("position_count", instrument_id), self._rows.pop(0))

    def request_close(self, instrument_id):
        if self._clock is not None:
            self._clock.advance(self._seconds_per_close)
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

    def still_closing(self, symbol, open_positions, seconds):
        self._journal.append(("still closing", symbol, open_positions, seconds))

    def unlocked(self):
        self._journal.append(("unlocked",))


def signal(side=Side.BUY, base_lot=0.01, symbol="XAUUSD"):
    return OpenSignal(symbol=symbol, side=side, sizing=LotSizing(base_lot=base_lot, balance_step=100.0),
                      take_profit=500, stop_loss=1000)


CLOSE_SIGNAL = CloseSignal(symbol="XAUUSD")


def use_case(journal, **broker_args):
    clock = FakeClock(journal.append)
    return ExecuteSignal(FakeBroker(journal, clock=clock, **broker_args), FakeConsole(journal), clock)


def execute(sig, **broker_args):
    journal = []
    result = use_case(journal, **broker_args).execute(sig)
    return result, journal


def run(sig, **broker_args):
    result, journal = execute(sig, **broker_args)
    assert result == Ok(None)
    return journal


LOOKUP = ("instrument_id", "XAUUSD")
START = [("balance",), LOOKUP, ("locked",)]
NO_ROWS = ("position_count", XAUUSD)
PAUSE = ("sleep", 1.0)
PLACE = ("place", XAUUSD, 0.1, Side.BUY, 1000, 500)
