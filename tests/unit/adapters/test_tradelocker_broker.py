"""``TradeLockerBroker`` against the fake that binds every call to the real
``TLAPI`` signature, so the requests are the ones the client receives.

The fake is built directly rather than through the characterization harness,
which imports the legacy entrypoint; adapter tests must not depend on it.
"""

import pytest

from tests.characterization.fake_tradelocker import NO_BALANCE_FIELD, FakeTradeLocker
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker

GOLD, EURO = 11, 22


def client(balance=1000.0, open_positions=(), order_results=(9001,)):
    return FakeTradeLocker(
        balance=balance,
        instrument_ids={"XAUUSD": GOLD, "EURUSD": EURO},
        open_positions=open_positions,
        order_results=order_results,
    )


@pytest.mark.parametrize(("balance", "expected"), [(1234.5, 1234.5), (None, None), (NO_BALANCE_FIELD, None)])
def test_balance_is_the_projected_balance_uncoerced(balance, expected):
    fake = client(balance=balance)

    assert TradeLockerBroker(fake).account_balance() == expected
    assert fake.calls == [("get_account_state",)]


def test_balance_keeps_the_reported_type():
    assert type(TradeLockerBroker(client(balance=1000)).account_balance()) is int


def test_instrument_id_is_looked_up_by_symbol_name():
    fake = client()

    assert TradeLockerBroker(fake).instrument_id("EURUSD") == EURO
    assert fake.calls == [("get_instrument_id_from_symbol_name", "EURUSD")]


def test_open_position_count_counts_only_the_instruments_rows():
    fake = client(open_positions=[GOLD, EURO, GOLD])

    assert TradeLockerBroker(fake).open_position_count(GOLD) == 2
    assert TradeLockerBroker(fake).open_position_count(33) == 0
    assert fake.calls == [("get_all_positions",), ("get_all_positions",)]


@pytest.mark.parametrize("instrument_id", [GOLD, EURO])
def test_request_close_passes_the_instrument_as_the_close_filter(instrument_id):
    fake = client(open_positions=[GOLD, EURO])

    TradeLockerBroker(fake).request_close(instrument_id)

    assert fake.calls == [("close_all_positions", instrument_id)]


def test_market_order_uses_offset_protection_and_client_defaults():
    fake = client(order_results=(9001,))

    order_id = TradeLockerBroker(fake).place_market_order(GOLD, 0.1, "sell", stop_loss=1000, take_profit=500)

    assert order_id == 9001
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
        GOLD, 0.1, "buy", stop_loss=1000, take_profit=500
    ) is None
