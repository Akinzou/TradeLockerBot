"""``TradeLockerBroker`` against the fake that binds every call to the real
``TLAPI`` signature, so the requests are the ones the client receives.

The fake is built directly rather than through the characterization harness,
which imports the legacy entrypoint; adapter tests must not depend on it.
"""

import pandas as pd
import pytest
from tradelocker.exceptions import TLAPIException

from tests.characterization.fake_tradelocker import NO_BALANCE_FIELD, FakeTradeLocker
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker
from tradelocker_bot.application.ports import BrokerFailure
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


@pytest.mark.parametrize(("balance", "expected"), [(1234.5, 1234.5), (None, None), (NO_BALANCE_FIELD, None)])
def test_balance_is_the_projected_balance_uncoerced(balance, expected):
    fake = client(balance=balance)

    assert TradeLockerBroker(fake).account_balance() == Ok(expected)
    assert fake.calls == [("get_account_state",)]


def test_balance_keeps_the_reported_type():
    assert type(TradeLockerBroker(client(balance=1000)).account_balance().value) is int


def test_instrument_id_is_looked_up_by_symbol_name():
    fake = client()

    assert TradeLockerBroker(fake).instrument_id("EURUSD") == Ok(EURO)
    assert fake.calls == [("get_instrument_id_from_symbol_name", "EURUSD")]


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


def test_market_order_returns_a_missing_id_unchanged():
    assert TradeLockerBroker(client(order_results=(None,))).place_market_order(
        GOLD, 0.1, Side.BUY, stop_loss=1000, take_profit=500
    ) == Ok(None)


CALLS = {
    "get_account_state": lambda broker: broker.account_balance(),
    "get_instrument_id_from_symbol_name": lambda broker: broker.instrument_id("XAUUSD"),
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


def test_an_unknown_symbol_is_a_failure_too():
    result = TradeLockerBroker(client()).instrument_id("GBPUSD")

    assert isinstance(result, Err)
    assert type(result.error.cause) is ValueError


def test_an_interrupt_is_not_turned_into_a_failure():
    # Only `Exception` is the broker's; Ctrl+C and interpreter exit must still stop the thread.
    with pytest.raises(KeyboardInterrupt):
        TradeLockerBroker(client(failures={("get_account_state", 1): KeyboardInterrupt()})).account_balance()


class AnswersWithoutTheExpectedShape:
    def get_account_state(self):
        return None

    def get_all_positions(self):
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
