"""Payloads that legacy code mishandled, as roadmap step 3 decides them
(ADR 0008). Payloads that are now refused, before any broker call or once
the broker has answered (ADR 0009), are in ``test_rejected_signals``; these
are the ones that still trade, and what they trade.
"""

import pytest

from tests.characterization.harness import XAUUSD_ID, broker, handle, payload


@pytest.mark.parametrize(
    ("direction", "invert", "side"),
    [
        # Before step 3, "Buy" with Invert opened a buy, and with NonInvert it
        # was sent to the broker as "Buy".
        ("Buy", "Invert", "sell"),
        ("Buy", "NonInvert", "buy"),
        (" SELL ", "NonInvert", "sell"),
        ("Sell", "Invert", "buy"),
    ],
)
def test_direction_case_and_spaces_do_not_change_the_side(direction, invert, side):
    fake = broker(open_positions=[XAUUSD_ID])

    handle(fake, payload(direction=direction, invert=invert))

    assert fake.orders()[0][2]["side"] == side


def test_spaces_around_the_lot_numbers_are_still_accepted():
    fake = broker()

    handle(fake, payload(lot=" 0.01 / 100 "))

    assert fake.orders()[0][2]["quantity"] == 0.1
