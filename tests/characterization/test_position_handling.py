"""Characterization tests: they pin what ``handle_position_normal`` does today.

They are a safety net for the incremental migration, not a specification.
Behaviour that looks wrong is still pinned here on purpose; changing it is a
separate, explicitly reviewed step (see docs/migration-roadmap.md).
"""

import pytest
from tradelocker.exceptions import TLAPIOrderException

from tests.characterization.harness import EURUSD_ID, XAUUSD_ID
from tests.characterization.harness import broker as _broker
from tests.characterization.harness import handle as _handle
from tests.characterization.harness import payload as _payload


def test_open_places_market_order_with_offset_protection():
    broker = _broker()

    _handle(broker, _payload())

    [(_, instrument_id, order)] = broker.orders()
    assert instrument_id == XAUUSD_ID
    assert order == {
        "quantity": 0.1,
        "side": "buy",
        "type_": "market",
        "stop_loss": 1000,
        "take_profit": 500,
        "stop_loss_type": "offset",
        "take_profit_type": "offset",
    }


@pytest.mark.parametrize(
    ("balance", "lot", "expected_quantity"),
    [
        (1000.0, "0.01/100", 0.1),
        (1234.0, "0.01/100", 0.12),
        (5000.0, "0.5/1000", 2.5),
    ],
)
def test_quantity_scales_with_projected_balance(balance, lot, expected_quantity):
    broker = _broker(balance=balance)

    _handle(broker, _payload(lot=lot))

    assert broker.orders()[0][2]["quantity"] == expected_quantity


@pytest.mark.parametrize(
    ("direction", "invert", "expected_side"),
    [
        ("buy", "NonInvert", "buy"),
        ("sell", "NonInvert", "sell"),
        ("buy", "Invert", "sell"),
        ("sell", "Invert", "buy"),
    ],
)
def test_invert_flag_controls_order_side(direction, invert, expected_side):
    broker = _broker()

    _handle(broker, _payload(direction=direction, invert=invert))

    assert broker.orders()[0][2]["side"] == expected_side


def test_open_closes_same_instrument_positions_before_ordering():
    broker = _broker(open_positions=[XAUUSD_ID, EURUSD_ID])

    _handle(broker, _payload())

    names = [call[0] for call in broker.calls]
    assert names.index("close_all_positions") < names.index("create_order")
    assert broker.open_positions == [EURUSD_ID]


def test_close_closes_positions_without_ordering():
    broker = _broker(open_positions=[XAUUSD_ID])

    _handle(broker, _payload(action="close"))

    assert broker.open_positions == []
    assert broker.orders() == []


@pytest.mark.parametrize("action", ["hold", "Open", "OPEN", "Close", " open"])
def test_unknown_action_neither_closes_nor_orders(action):
    broker = _broker(open_positions=[XAUUSD_ID])

    _handle(broker, _payload(action=action))

    assert broker.open_positions == [XAUUSD_ID]
    assert broker.orders() == []


def test_broker_rejection_propagates_after_existing_position_was_closed():
    rejection = TLAPIOrderException({}, {"errmsg": "Not enough margin"})
    broker = _broker(open_positions=[XAUUSD_ID], order_results=(rejection,))

    with pytest.raises(TLAPIOrderException):
        _handle(broker, _payload())

    assert broker.open_positions == []
    assert len(broker.orders()) == 1


def test_close_request_is_resent_on_every_poll_until_the_broker_fills_it():
    broker = _broker(open_positions=[XAUUSD_ID], close_requests_to_fill=3)

    _handle(broker, _payload(action="close"))

    closes = [call for call in broker.calls if call[0] == "close_all_positions"]
    assert len(closes) == 3
    assert broker.open_positions == []


def test_invalid_invert_value_raises_after_existing_position_was_closed():
    broker = _broker(open_positions=[XAUUSD_ID])

    with pytest.raises(ValueError, match="isInvert"):
        _handle(broker, _payload(invert="Sideways"))

    assert broker.open_positions == []
    assert broker.orders() == []


def test_truncated_payload_raises_index_error():
    broker = _broker()

    with pytest.raises(IndexError):
        _handle(broker, _payload()[:5])

    assert broker.orders() == []


def test_non_numeric_take_profit_raises_before_touching_the_broker():
    broker = _broker()

    with pytest.raises(ValueError):
        _handle(broker, _payload(tp="abc"))

    assert broker.calls == []
