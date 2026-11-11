from typing import Callable, TypeVar

from tradelocker import TLAPI

from tradelocker_bot.application.ports import BrokerFailure
from tradelocker_bot.domain.result import Err, Ok, Result

T = TypeVar("T")


def _answer(client_call: Callable[[], T]) -> Result[T, BrokerFailure]:
    # `Exception`, not a list of client exceptions: the client raises its own
    # `TLAPIException`, a bare `ValueError` for an unknown symbol, and whatever
    # `requests` and pandas raise underneath, so a narrower list would let an
    # unlisted failure escape as an exception after all. `BaseException` stays
    # out: an interrupt or interpreter exit is not the broker's answer.
    # Only the client call goes in here; the adapter's own handling of the
    # answer stays outside, so a bug in it raises instead of posing as an
    # outage.
    try:
        return Ok(client_call())
    except Exception as error:
        return Err(BrokerFailure(error))


class TradeLockerBroker:
    """The ``Broker`` port over the TradeLocker client (ADR 0005, ADR 0006).

    Each method is the legacy handler's call, unchanged: the same arguments
    and defaults left to the client. A client exception comes back as
    ``Err(BrokerFailure)`` holding that very exception object.
    """

    def __init__(self, client: TLAPI):
        self._client = client

    def account_balance(self) -> Result[float | None, BrokerFailure]:
        # `.get`, not `[...]`: the client builds the state from the broker's
        # column list, so a missing field must surface as `None`, as before.
        state = _answer(self._client.get_account_state)
        if isinstance(state, Err):
            return state
        return Ok(state.value.get("projectedBalance"))

    def instrument_id(self, symbol: str) -> Result[int, BrokerFailure]:
        return _answer(lambda: self._client.get_instrument_id_from_symbol_name(symbol))

    def open_position_count(self, instrument_id: int) -> Result[int, BrokerFailure]:
        positions = _answer(self._client.get_all_positions)
        if isinstance(positions, Err):
            return positions
        rows = positions.value
        return Ok(len(rows[rows["tradableInstrumentId"] == instrument_id]))

    def request_close(self, instrument_id: int) -> Result[None, BrokerFailure]:
        def close() -> None:
            # The client's return value is dropped, as the legacy handler dropped it.
            self._client.close_all_positions(instrument_id)

        return _answer(close)

    def place_market_order(
        self, instrument_id: int, quantity: float, side: str, stop_loss: int, take_profit: int
    ) -> Result[int | None, BrokerFailure]:
        return _answer(lambda: self._client.create_order(
            instrument_id,
            quantity=quantity,
            side=side,
            type_="market",
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_type="offset",
            take_profit_type="offset",
        ))
