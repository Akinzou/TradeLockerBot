import pytest

from tradelocker_bot.domain.lot_sizing import LotSizing


def test_parses_base_lot_per_balance_step():
    assert LotSizing.parse("0.01/100") == LotSizing(base_lot=0.01, balance_step=100.0)


def test_parsing_tolerates_whitespace_around_numbers():
    assert LotSizing.parse(" 0.01 / 100 ") == LotSizing(base_lot=0.01, balance_step=100.0)


@pytest.mark.parametrize("text", ["0.01", "abc/100", "0.01/100/2", ""])
def test_rejects_text_that_is_not_two_numbers(text):
    with pytest.raises(ValueError):
        LotSizing.parse(text)


@pytest.mark.parametrize(
    ("balance", "expected"),
    [(1000.0, 0.1), (1234.0, 0.12), (10.0, 0.0)],
)
def test_quantity_scales_with_balance_rounded_to_two_decimals(balance, expected):
    assert LotSizing(base_lot=0.01, balance_step=100.0).quantity_for(balance) == expected


def test_is_immutable():
    sizing = LotSizing(base_lot=0.01, balance_step=100.0)

    with pytest.raises(AttributeError):
        sizing.base_lot = 1.0
