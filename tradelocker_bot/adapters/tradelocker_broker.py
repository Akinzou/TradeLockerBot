from tradelocker import TLAPI


class TradeLockerBroker:
    """The ``Broker`` port over the TradeLocker client (ADR 0005).

    Each method is the legacy handler's call, unchanged: the same arguments,
    defaults left to the client, and the client's exceptions propagated.
    """

    def __init__(self, client: TLAPI):
        self._client = client

    def account_balance(self) -> object:
        # `.get`, not `[...]`: the client builds the state from the broker's
        # column list, so a missing field must surface as `None`, as before.
        return self._client.get_account_state().get("projectedBalance")

    def instrument_id(self, symbol: str) -> int:
        return self._client.get_instrument_id_from_symbol_name(symbol)

    def open_position_count(self, instrument_id: int) -> int:
        positions = self._client.get_all_positions()
        return len(positions[positions["tradableInstrumentId"] == instrument_id])

    def request_close(self, instrument_id: int) -> None:
        self._client.close_all_positions(instrument_id)

    def place_market_order(
        self, instrument_id: int, quantity: float, side: str, stop_loss: int, take_profit: int
    ) -> object:
        return self._client.create_order(
            instrument_id,
            quantity=quantity,
            side=side,
            type_="market",
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_type="offset",
            take_profit_type="offset",
        )
