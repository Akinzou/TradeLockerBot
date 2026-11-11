"""The fake is only a safe stand-in while it refuses calls the real client refuses."""

import importlib.util

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



def test_fake_records_the_request_not_the_spelling_of_the_call():
    positional, keyword = _fake(), _fake()
    positional.create_order(1, 0.1, "buy")
    keyword.create_order(instrument_id=1, quantity=0.1, side="buy", type_="market")

    assert positional.calls == keyword.calls
    [(_, instrument_id, order)] = positional.calls
    assert instrument_id == 1
    assert order["quantity"] == 0.1 and order["side"] == "buy" and order["type_"] == "market"
    assert "instrument_id" not in order

def test_tradelocker_runs_without_runtime_type_checks():
    # The fake skips type checks because production does (see its docstring).
    # If a dependency ever pulls in typeguard, TLAPI starts rejecting values the
    # fake accepts, and every pin about unvalidated arguments becomes fiction.
    assert importlib.util.find_spec("typeguard") is None
