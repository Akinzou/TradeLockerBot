from typing import Callable, TypeVar

from tradelocker import TLAPI

from tradelocker_bot.application.ports import BrokerFailure
from tradelocker_bot.domain.result import Err, Ok, Result
from tradelocker_bot.domain.signal import Side

T = TypeVar("T")


def _answer(client_call: Callable[[], T]) -> Result[T, BrokerFailure]:
    # `Exception`, not a list of client exceptions: the client raises its own
    # `TLAPIException` and whatever `requests` and pandas raise underneath, so
    # a narrower list would let an unlisted failure escape as an exception
    # after all. `BaseException` stays out: an interrupt or interpreter exit
    # is not the broker's answer.
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
    and defaults left to the client. The exception is the instrument lookup,
    which reads the instrument list instead (ADR 0009). A client exception
    comes back as ``Err(BrokerFailure)`` holding that very exception object.
    """

    def __init__(self, client: TLAPI):
        self._client = client

    def account_balance(self) -> Result[float | None, BrokerFailure]:
        # `.get`, not `[...]`: the client builds the state from the broker's
        # column list, so the field can be absent rather than null.
        state = _answer(self._client.get_account_state)
        if isinstance(state, Err):
            return state
        balance = state.value.get("projectedBalance")
        # `bool` is an `int` to Python, but `true` is no balance.
        if isinstance(balance, (int, float)) and not isinstance(balance, bool):
            return Ok(balance)
        return Ok(None)

    def instrument_id(self, symbol: str) -> Result[int | None, BrokerFailure]:
        # The client's own lookup is not called: it raises a bare `ValueError`
        # for an unknown name, and the same bare `ValueError` for an answer
        # that is empty or not JSON, so telling them apart would mean matching the
        # message. The match below is the client's own (exact name, first of
        # several), pinned against it by the adapter tests (ADR 0009).
        instruments = _answer(self._client.get_all_instruments)
        if isinstance(instruments, Err):
            return instruments
        frame = instruments.value
        # An empty list comes without columns, so it has no `name` to match:
        # it lists no symbol, which the port reports as `None`, not a fault.
        if frame.empty:
            return Ok(None)
        matches = frame[frame["name"] == symbol]
        if matches.empty:
            return Ok(None)
        return Ok(int(matches["tradableInstrumentId"].iloc[0]))

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
        self, instrument_id: int, quantity: float, side: Side, stop_loss: int, take_profit: int
    ) -> Result[int | None, BrokerFailure]:
        return _answer(lambda: self._client.create_order(
            instrument_id,
            quantity=quantity,
            side=side.value,
            type_="market",
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_type="offset",
            take_profit_type="offset",
        ))
