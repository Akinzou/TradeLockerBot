"""``TradeLockerBroker`` against the fake that binds every call to the real
``TLAPI`` signature, so the requests are the ones the client receives."""

import pytest

from tests.characterization.fake_tradelocker import NO_BALANCE_FIELD
from tests.characterization.harness import DEFAULT_ORDER, EURUSD_ID, XAUUSD_ID, broker
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker


@pytest.mark.parametrize(("balance", "expected"), [(1234.5, 1234.5), (None, None), (NO_BALANCE_FIELD, None)])
def test_balance_is_the_projected_balance_uncoerced(balance, expected):
    fake = broker(balance=balance)

    assert TradeLockerBroker(fake).account_balance() == expected
    assert fake.calls == [("get_account_state",)]


def test_balance_keeps_the_reported_type():
    assert type(TradeLockerBroker(broker(balance=1000)).account_balance()) is int


def test_instrument_id_is_looked_up_by_symbol_name():
    fake = broker()

    assert TradeLockerBroker(fake).instrument_id("EURUSD") == EURUSD_ID
    assert fake.calls == [("get_instrument_id_from_symbol_name", "EURUSD")]


def test_open_position_count_counts_only_the_instruments_rows():
    fake = broker(open_positions=[XAUUSD_ID, EURUSD_ID, XAUUSD_ID])

    assert TradeLockerBroker(fake).open_position_count(XAUUSD_ID) == 2
    assert TradeLockerBroker(fake).open_position_count(303) == 0
    assert fake.calls == [("get_all_positions",), ("get_all_positions",)]


def test_request_close_filters_by_instrument():
    fake = broker(open_positions=[XAUUSD_ID])

    TradeLockerBroker(fake).request_close(XAUUSD_ID)

    assert fake.calls == [("close_all_positions", XAUUSD_ID)]


def test_market_order_uses_offset_protection():
    fake = broker(order_results=(9001,))

    order_id = TradeLockerBroker(fake).place_market_order(
        XAUUSD_ID, 0.1, "buy", stop_loss=1000, take_profit=500
    )

    assert order_id == 9001
    assert fake.calls == [("create_order", XAUUSD_ID, DEFAULT_ORDER)]


def test_market_order_returns_a_missing_id_unchanged():
    assert TradeLockerBroker(broker(order_results=(None,))).place_market_order(
        XAUUSD_ID, 0.1, "buy", stop_loss=1000, take_profit=500
    ) is None
