"""``ExecuteSignal`` against in-memory ports that share one journal, so the
order of broker calls and console lines relative to each other is checked."""

import pytest

from tradelocker_bot.application.execute_signal import ExecuteSignal, TradeSignal

XAUUSD = 101


class Rejected(Exception):
    pass


class FakeBroker:
    def __init__(self, journal, balance=1000.0, rows=(0,), order_results=(9001,)):
        self._journal = journal
        self._balance = balance
        self._rows = list(rows)
        self._order_results = list(order_results)

    def account_balance(self):
        self._journal.append(("balance",))
        return self._balance

    def instrument_id(self, symbol):
        self._journal.append(("instrument_id", symbol))
        return XAUUSD

    def open_position_count(self, instrument_id):
        self._journal.append(("position_count", instrument_id))
        return self._rows.pop(0)

    def request_close(self, instrument_id):
        self._journal.append(("request_close", instrument_id))

    def place_market_order(self, instrument_id, quantity, side, stop_loss, take_profit):
        self._journal.append(("place", instrument_id, quantity, side, stop_loss, take_profit))
        result = self._order_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


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


def signal(action="open", direction="buy", lot="0.01/100", invert="NonInvert"):
    return TradeSignal(symbol="XAUUSD", direction=direction, lot=lot, take_profit=500,
                       stop_loss=1000, action=action, invert=invert)


def run(sig, **broker_args):
    journal = []
    ExecuteSignal(FakeBroker(journal, **broker_args), FakeConsole(journal)).execute(sig)
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
PLACE = ("place", XAUUSD, 0.1, "buy", 1000, 500)


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


def test_close_closes_without_a_second_lookup_or_an_order():
    assert run(signal(action="close"), rows=(1, 0)) == [
        *START, LOOKUP, NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), NO_ROWS, ("unlocked",),
    ]


@pytest.mark.parametrize("action", ["hold", "Open", " open", ""])
def test_any_other_action_only_reads_the_balance(action):
    assert run(signal(action=action, invert="Sideways")) == [*START, ("unlocked",)]


def test_quantity_is_sized_from_the_balance():
    assert run(signal(), balance=1234.0)[5] == ("place", XAUUSD, 0.12, "buy", 1000, 500)


def test_inverted_side_is_ordered_and_named_in_the_retry_line():
    journal = run(signal(invert="Invert"), order_results=(None, 0, 9001))

    assert journal[4:] == [
        LOOKUP,
        ("place", XAUUSD, 0.1, "sell", 1000, 500), ("retry", "sell"),
        ("place", XAUUSD, 0.1, "sell", 1000, 500), ("retry", "sell"),
        ("place", XAUUSD, 0.1, "sell", 1000, 500), ("placed", 9001),
        ("unlocked",),
    ]


def test_invalid_invert_fails_after_closing_and_the_second_lookup():
    journal = run_raising(signal(invert="Sideways"), ValueError, rows=(1, 0))

    assert journal == [*START, LOOKUP, NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), NO_ROWS, LOOKUP]


@pytest.mark.parametrize(("lot", "error"), [("abc/100", ValueError), ("0.01/0", ZeroDivisionError)])
def test_malformed_lot_fails_after_the_balance_before_locked(lot, error):
    assert run_raising(signal(lot=lot), error) == [("balance",)]


def test_balance_reaches_the_lot_sizing_uncoerced():
    assert run_raising(signal(), TypeError, balance=None) == [("balance",)]


def test_broker_rejection_propagates_without_unlocked():
    journal = run_raising(signal(), Rejected, order_results=(Rejected(),))

    assert journal[-1] == PLACE
