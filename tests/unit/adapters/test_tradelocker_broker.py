"""``TradeLockerBroker`` against the fake that binds every call to the real
``TLAPI`` signature, so the requests are the ones the client receives.

The fake is built directly rather than through the characterization harness,
which imports the legacy entrypoint; adapter tests must not depend on it.
"""

import logging

import pandas as pd
import pytest
from tradelocker import TLAPI
from tradelocker.exceptions import TLAPIException, TLAPIOrderException

from tests.characterization.fake_tradelocker import NO_BALANCE_FIELD, FakeTradeLocker
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker
from tradelocker_bot.application.ports import BrokerFailure, OrderRejected
from tradelocker_bot.domain.result import Err, Ok
from tradelocker_bot.domain.signal import Side

GOLD, EURO = 11, 22


def client(balance=1000.0, open_positions=(), order_results=(9001,), failures=None):
    return FakeTradeLocker(
        balance=balance,
        instrument_ids={"XAUUSD": GOLD, "EURUSD": EURO},
        open_positions=open_positions,
        order_results=order_results,
        failures=failures,
    )


@pytest.mark.parametrize(("balance", "expected"), [(1234.5, 1234.5), (0, 0), (-50.0, -50.0)])
def test_a_numeric_balance_is_the_projected_balance_uncoerced(balance, expected):
    fake = client(balance=balance)

    assert TradeLockerBroker(fake).account_balance() == Ok(expected)
    assert fake.calls == [("get_account_state",)]


@pytest.mark.parametrize("balance", [None, NO_BALANCE_FIELD, "1000", True, [1000.0]])
def test_a_balance_that_is_not_a_number_is_reported_as_none(balance):
    # Coercing "1000" would guess at what the broker meant; the use case
    # refuses the signal instead (ADR 0009).
    assert TradeLockerBroker(client(balance=balance)).account_balance() == Ok(None)


def test_balance_keeps_the_reported_type():
    assert type(TradeLockerBroker(client(balance=1000)).account_balance().value) is int


def test_instrument_id_is_looked_up_by_symbol_name_in_the_instrument_list():
    fake = client()

    assert TradeLockerBroker(fake).instrument_id("EURUSD") == Ok(EURO)
    assert fake.calls == [("get_all_instruments",)]


@pytest.mark.parametrize("symbol", ["GBPUSD", "xauusd", " XAUUSD", ""])
def test_a_symbol_the_broker_does_not_list_is_none_not_a_failure(symbol):
    assert TradeLockerBroker(client()).instrument_id(symbol) == Ok(None)


def test_an_empty_instrument_list_lists_no_symbol():
    # The client builds it from an empty JSON list, so it has no columns.
    assert TradeLockerBroker(AnswersWithoutTheExpectedShape()).instrument_id("XAUUSD") == Ok(None)


class InstrumentList:
    """Just what the client's own lookup reads from ``self``."""

    log = logging.getLogger(__name__)

    def __init__(self, names):
        self._frame = pd.DataFrame({
            "tradableInstrumentId": pd.Series(range(1, len(names) + 1), dtype="int64"),
            "name": names,
        })

    def get_all_instruments(self):
        return self._frame


@pytest.mark.parametrize(
    ("names", "symbol"),
    [(["XAUUSD", "EURUSD"], "EURUSD"), (["XAUUSD", "EURUSD", "XAUUSD"], "XAUUSD"), (["XAUUSD"], "GBPUSD")],
)
def test_the_lookup_answers_what_the_clients_own_lookup_answers(names, symbol):
    # The adapter repeats the client's match instead of calling it, so this
    # pins the two together: a client upgrade that changes how a name is
    # matched fails here, not in production (ADR 0009).
    instruments = InstrumentList(names)
    try:
        expected = Ok(TLAPI.get_instrument_id_from_symbol_name(instruments, symbol))
    except ValueError:
        expected = Ok(None)

    assert TradeLockerBroker(instruments).instrument_id(symbol) == expected


def test_open_position_count_counts_only_the_instruments_rows():
    fake = client(open_positions=[GOLD, EURO, GOLD])

    assert TradeLockerBroker(fake).open_position_count(GOLD) == Ok(2)
    assert TradeLockerBroker(fake).open_position_count(33) == Ok(0)
    assert fake.calls == [("get_all_positions",), ("get_all_positions",)]


@pytest.mark.parametrize("instrument_id", [GOLD, EURO])
def test_request_close_passes_the_instrument_as_the_close_filter(instrument_id):
    fake = client(open_positions=[GOLD, EURO])

    assert TradeLockerBroker(fake).request_close(instrument_id) == Ok(None)
    assert fake.calls == [("close_all_positions", instrument_id)]


def test_market_order_uses_offset_protection_and_client_defaults():
    fake = client(order_results=(9001,))

    order_id = TradeLockerBroker(fake).place_market_order(GOLD, 0.1, Side.SELL, stop_loss=1000, take_profit=500)

    assert order_id == Ok(9001)
    assert fake.calls == [("create_order", GOLD, {
        "quantity": 0.1,
        "side": "sell",
        "price": None,
        "type_": "market",
        "validity": None,
        "position_netting": False,
        "take_profit": 500,
        "take_profit_type": "offset",
        "stop_loss": 1000,
        "stop_loss_type": "offset",
        "stop_price": None,
        "strategy_id": None,
        "_ignore_len_check": False,
    })]


def test_a_market_order_answered_without_an_id_is_a_rejection_with_no_reason():
    # The client returns None only when it created no order; its one such path,
    # netting, is never enabled, but the port promises an id for every `Ok`.
    assert TradeLockerBroker(client(order_results=(None,))).place_market_order(
        GOLD, 0.1, Side.BUY, stop_loss=1000, take_profit=500
    ) == Err(OrderRejected(None))


def test_an_order_id_of_zero_is_an_order_id():
    assert TradeLockerBroker(client(order_results=(0,))).place_market_order(
        GOLD, 0.1, Side.BUY, stop_loss=1000, take_profit=500
    ) == Ok(0)


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ({"s": "error", "errmsg": "Not enough margin"}, "Not enough margin"),
        ({"s": "error"}, None),
        ({"s": "error", "errmsg": ""}, None),
        ({"s": "error", "errmsg": None}, None),
        ({"s": "error", "errmsg": ["Not enough margin"]}, None),
        # The client's own `str()` of the exception raises a TypeError on this one.
        ("errmsg", None),
        (["errmsg"], None),
    ],
)
def test_an_order_the_broker_rejects_is_a_rejection_with_the_brokers_reason_only(answer, reason):
    # The client raises TLAPIOrderException when the broker answered without
    # an order id. Only `errmsg` is taken: the rest of the answer, which the
    # exception's own text prints whole, is not the operator's to read.
    rejection = TLAPIOrderException({"qty": "0.1"}, answer)
    broker = TradeLockerBroker(client(failures={("create_order", 1): rejection}))

    assert broker.place_market_order(GOLD, 0.1, Side.BUY, stop_loss=1000, take_profit=500) == Err(
        OrderRejected(reason)
    )


CALLS = {
    "get_account_state": lambda broker: broker.account_balance(),
    "get_all_instruments": lambda broker: broker.instrument_id("XAUUSD"),
    "get_all_positions": lambda broker: broker.open_position_count(GOLD),
    "close_all_positions": lambda broker: broker.request_close(GOLD),
    "create_order": lambda broker: broker.place_market_order(GOLD, 0.1, Side.BUY, stop_loss=1000, take_profit=500),
}


@pytest.mark.parametrize("client_call", CALLS)
def test_a_client_exception_comes_back_as_a_failure_holding_that_exception(client_call):
    failure = TLAPIException("broker unavailable")

    result = CALLS[client_call](TradeLockerBroker(client(failures={(client_call, 1): failure})))

    assert result == Err(BrokerFailure(failure))
    assert result.error.cause is failure


def test_an_interrupt_is_not_turned_into_a_failure():
    # Only `Exception` is the broker's; Ctrl+C and interpreter exit must still stop the thread.
    with pytest.raises(KeyboardInterrupt):
        TradeLockerBroker(client(failures={("get_account_state", 1): KeyboardInterrupt()})).account_balance()


class AnswersWithoutTheExpectedShape:
    def get_account_state(self):
        return None

    def get_all_positions(self):
        return pd.DataFrame()

    def get_all_instruments(self):
        return pd.DataFrame()


@pytest.mark.parametrize(
    ("read", "error"),
    [
        (lambda broker: broker.account_balance(), AttributeError),
        (lambda broker: broker.open_position_count(GOLD), KeyError),
    ],
)
def test_a_fault_in_handling_the_answer_raises_rather_than_posing_as_an_outage(read, error):
    with pytest.raises(error):
        read(TradeLockerBroker(AnswersWithoutTheExpectedShape()))
