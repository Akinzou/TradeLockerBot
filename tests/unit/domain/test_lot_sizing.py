import math

import pytest

from tradelocker_bot.domain.lot_sizing import LotSizing, UnusableQuantity
from tradelocker_bot.domain.result import Err, Ok


def test_parses_base_lot_per_balance_step():
    assert LotSizing.parse("0.01/100") == LotSizing(base_lot=0.01, balance_step=100.0)


def test_parsing_tolerates_whitespace_around_numbers():
    assert LotSizing.parse(" 0.01 / 100 ") == LotSizing(base_lot=0.01, balance_step=100.0)


@pytest.mark.parametrize("text", ["0.01", "abc/100", "0.01/100/2", "", "/", "0.01/"])
def test_text_that_is_not_two_numbers_parses_to_none(text):
    assert LotSizing.parse(text) is None


@pytest.mark.parametrize("text", ["0/100", "-0.01/100", "0.01/0", "0.01/-100", "inf/100", "0.01/inf", "nan/100"])
def test_numbers_that_cannot_size_a_position_parse_to_none(text):
    assert LotSizing.parse(text) is None


@pytest.mark.parametrize(
    ("base_lot", "balance_step"),
    [(0.0, 100.0), (-0.01, 100.0), (0.01, 0.0), (float("inf"), 100.0), (0.01, float("nan"))],
)
def test_cannot_be_built_from_numbers_that_cannot_size_a_position(base_lot, balance_step):
    with pytest.raises(ValueError, match="positive finite"):
        LotSizing(base_lot=base_lot, balance_step=balance_step)


@pytest.mark.parametrize(
    ("balance", "expected"),
    [(1000.0, 0.1), (1234.0, 0.12), (50.0, 0.01), (1000, 0.1)],
)
def test_quantity_scales_with_balance_rounded_to_two_decimals(balance, expected):
    assert LotSizing(base_lot=0.01, balance_step=100.0).quantity_for(balance) == Ok(expected)


@pytest.mark.parametrize(
    ("sizing", "balance", "quantity"),
    [
        # Too small a balance: the quantity rounds to zero.
        (LotSizing(base_lot=0.01, balance_step=100.0), 10.0, 0.0),
        (LotSizing(base_lot=0.01, balance_step=100.0), 0.0, 0.0),
        (LotSizing(base_lot=0.01, balance_step=100.0), -500.0, -0.05),
        # Two valid numbers whose product overflows.
        (LotSizing(base_lot=1e306, balance_step=1.0), 1000.0, math.inf),
        (LotSizing(base_lot=0.01, balance_step=100.0), -math.inf, -math.inf),
    ],
)
def test_a_quantity_the_broker_cannot_trade_is_refused(sizing, balance, quantity):
    assert sizing.quantity_for(balance) == Err(UnusableQuantity(balance=balance, quantity=quantity))


@pytest.mark.parametrize(
    ("balance", "usable"),
    [(10.0, True), (1e-9, True), (0.0, False), (-500.0, False), (math.inf, False), (math.nan, False)],
)
def test_names_whether_the_balance_is_what_rules_the_quantity_out(balance, usable):
    assert UnusableQuantity(balance=balance, quantity=0.0).balance_is_usable is usable


def test_a_balance_that_is_not_a_number_gives_no_quantity():
    result = LotSizing(base_lot=0.01, balance_step=100.0).quantity_for(math.nan)

    assert isinstance(result, Err)
    assert math.isnan(result.error.quantity)


def test_is_immutable():
    sizing = LotSizing(base_lot=0.01, balance_step=100.0)

    with pytest.raises(AttributeError):
        sizing.base_lot = 1.0
