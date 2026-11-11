"""Characterization of malformed webhook payloads that today's code accepts or
rejects in surprising ways. These pins exist so the domain extraction cannot
change them silently; correcting them is a separate, ADR-backed step.
"""

import math

import pytest

from tests.characterization.harness import XAUUSD_ID, broker, handle, payload


def test_invert_with_unexpected_direction_case_opens_a_buy():
    fake = broker(open_positions=[XAUUSD_ID])

    handle(fake, payload(direction="Buy", invert="Invert"))

    assert fake.orders()[0][2]["side"] == "buy"


def test_non_invert_forwards_unexpected_direction_to_the_broker_unchanged():
    # Pins only what the bot sends. How the broker answers side="Buy" is
    # unverified; if it rejects, the position closed above is not replaced.
    fake = broker(open_positions=[XAUUSD_ID])

    handle(fake, payload(direction="Buy", invert="NonInvert"))

    assert fake.orders()[0][2]["side"] == "Buy"


@pytest.mark.parametrize(
    ("lot", "error"),
    [
        ("0.01", ValueError),
        ("abc/100", ValueError),
        ("0.01/100/2", ValueError),
        ("0.01/0", ZeroDivisionError),
    ],
)
def test_malformed_lot_raises_after_reading_balance_before_touching_positions(lot, error):
    fake = broker(open_positions=[XAUUSD_ID])

    with pytest.raises(error):
        handle(fake, payload(lot=lot))

    assert [call[0] for call in fake.calls] == ["get_account_state"]
    assert fake.open_positions == [XAUUSD_ID]


@pytest.mark.parametrize(
    ("balance", "lot", "expected_quantity"),
    [
        (1000.0, "0/100", 0.0),
        (1000.0, "-0.01/100", -0.1),
        (1000.0, " 0.01 / 100 ", 0.1),
        (1000.0, "inf/100", math.inf),
        (10.0, "0.01/100", 0.0),
    ],
)
def test_nonsensical_lot_that_parses_is_sent_to_the_broker(balance, lot, expected_quantity):
    fake = broker(balance=balance)

    handle(fake, payload(lot=lot))

    assert fake.orders()[0][2]["quantity"] == expected_quantity


def test_nan_lot_is_sent_to_the_broker():
    fake = broker()

    handle(fake, payload(lot="nan/100"))

    assert math.isnan(fake.orders()[0][2]["quantity"])
