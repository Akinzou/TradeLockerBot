"""The fake is only a safe stand-in while it refuses calls the real client refuses."""

import pytest

from tests.characterization.fake_tradelocker import FakeTradeLocker


def _fake():
    return FakeTradeLocker(balance=1000.0, instrument_ids={"XAUUSD": 1})


def test_fake_rejects_keyword_the_real_create_order_does_not_have():
    with pytest.raises(TypeError):
        _fake().create_order(1, quantity=0.1, side="buy", takeprofit=500)


def test_fake_rejects_missing_required_create_order_argument():
    with pytest.raises(TypeError):
        _fake().create_order(1, side="buy")


def test_fake_rejects_keyword_the_real_close_all_positions_does_not_have():
    with pytest.raises(TypeError):
        _fake().close_all_positions(instrument_id=1)
