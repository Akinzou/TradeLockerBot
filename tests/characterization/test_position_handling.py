"""Characterization tests: they pin what the webhook's signal handler does today.

They are a safety net for the incremental migration, not a specification.
Behaviour that looks wrong is still pinned here on purpose; changing it is a
separate, explicitly reviewed step (see docs/migration-roadmap.md).
"""

import pytest

from tests.characterization.harness import DEFAULT_ORDER, EURUSD_ID, XAUUSD_ID
from tests.characterization.harness import broker as _broker
from tests.characterization.harness import handle as _handle
from tests.characterization.harness import order_rejection
from tests.characterization.harness import payload as _payload


def test_open_places_market_order_with_offset_protection():
    broker = _broker()

    _handle(broker, _payload())

    [(_, instrument_id, order)] = broker.orders()
    assert instrument_id == XAUUSD_ID
    assert order == DEFAULT_ORDER


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


@pytest.mark.parametrize("action", ["Open", "OPEN", " open", "open "])
def test_open_ignores_case_and_spaces_in_the_action(action):
    # Before step 3 these were ignored like any unknown action (ADR 0008).
    broker = _broker(open_positions=[XAUUSD_ID])

    _handle(broker, _payload(action=action))

    assert broker.open_positions == []
    assert len(broker.orders()) == 1


@pytest.mark.parametrize("action", ["Close", " close", "close "])
def test_close_ignores_case_and_spaces_in_the_action(action):
    broker = _broker(open_positions=[XAUUSD_ID])

    _handle(broker, _payload(action=action))

    assert broker.open_positions == []
    assert broker.orders() == []


def test_a_rejected_order_after_the_close_leaves_no_position_and_raises_nothing():
    # Before step 6i the client's exception ended the webhook thread with a
    # traceback; the account was flat all the same (ADR 0021).
    broker = _broker(open_positions=[XAUUSD_ID], order_results=(order_rejection(), 9001))

    _handle(broker, _payload())

    assert broker.open_positions == []
    assert len(broker.orders()) == 1


def test_close_request_is_resent_on_every_poll_until_the_broker_fills_it():
    broker = _broker(open_positions=[XAUUSD_ID], close_requests_to_fill=3)

    _handle(broker, _payload(action="close"))

    closes = [call for call in broker.calls if call[0] == "close_all_positions"]
    assert len(closes) == 3
    assert broker.open_positions == []


def test_invalid_invert_value_keeps_the_existing_position():
    # Before step 3 it raised only after the position was closed, leaving the
    # account flat (ADR 0008).
    broker = _broker(open_positions=[XAUUSD_ID])

    _handle(broker, _payload(invert="Sideways"))

    assert broker.open_positions == [XAUUSD_ID]
    assert broker.calls == []
