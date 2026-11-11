import pytest

from tradelocker_bot.domain.order_side import order_side


@pytest.mark.parametrize(
    ("direction", "invert", "expected"),
    [
        ("buy", "NonInvert", "buy"),
        ("sell", "NonInvert", "sell"),
        ("buy", "Invert", "sell"),
        ("sell", "Invert", "buy"),
    ],
)
def test_keeps_or_reverses_the_direction(direction, invert, expected):
    assert order_side(direction, invert) == expected


def test_non_invert_passes_any_direction_through_unchanged():
    # Legacy behaviour, pinned in characterization; strict directions are step 3.
    assert order_side("Buy", "NonInvert") == "Buy"


def test_invert_turns_anything_but_exactly_buy_into_buy():
    assert order_side("Buy", "Invert") == "buy"


@pytest.mark.parametrize("invert", ["Sideways", "invert", " Invert", ""])
def test_rejects_an_unknown_invert_flag(invert):
    with pytest.raises(ValueError, match=r"^Invalid value for isInvert\. Expected 'NonInvert' or 'Invert'\.$"):
        order_side("buy", invert)
