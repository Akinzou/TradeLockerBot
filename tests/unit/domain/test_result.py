import pytest

from tradelocker_bot.domain.result import Err, Ok


def test_ok_and_err_carry_their_payload():
    assert Ok(3).value == 3
    assert Err("down").error == "down"


def test_results_compare_by_kind_and_payload():
    assert Ok(1) == Ok(1)
    assert Ok(1) != Err(1)
    assert Err("a") != Err("b")


@pytest.mark.parametrize("result", [Ok(0), Ok(None), Ok(9001), Err("down")])
def test_a_result_refuses_to_be_tested_for_truth(result):
    # `Ok(0)` would be truthy, so `while not order_id:` on an unwrapped result
    # would stop retrying silently; refusing makes the slip fail loudly.
    with pytest.raises(TypeError, match="unwrap"):
        bool(result)


def test_results_are_immutable():
    with pytest.raises(AttributeError):
        Ok(1).value = 2
