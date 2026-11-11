from tradelocker_bot.application.ports import Broker, BrokerFailure, OperatorConsole
from tradelocker_bot.application.refusal import NoBalance, Refusal, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.result import Err, Ok, Result
from tradelocker_bot.domain.signal import CloseSignal, OpenSignal, Side, Signal


class ExecuteSignal:
    """Close and open positions for one valid signal (ADR 0005, ADR 0008,
    ADR 0009).

    The signal is parsed before it gets here, so every payload error is
    already refused without a broker call. What only the broker can rule out,
    a missing balance, an unusable quantity, an unknown symbol, is refused
    here before the ``locked`` line and before any close request, so a
    refused signal never leaves the account flat. An order the broker itself
    rejects, below its minimum lot for one, still does: roadmap step 6.
    """

    def __init__(self, broker: Broker, console: OperatorConsole):
        self._broker = broker
        self._console = console

    def execute(self, signal: Signal) -> Result[None, BrokerFailure | Refusal]:
        """``Ok(None)`` once handled; otherwise the refusal, or the first
        broker failure, returned at once without ``unlocked`` (ADR 0006).

        ``close`` reads no balance: it sizes nothing (ADR 0008). The
        instrument is looked up once and its id used for both the close and
        the order; legacy looked it up again before ordering (ADR 0009).
        """
        if isinstance(signal, CloseSignal):
            instrument_id = self._listed_instrument(signal.symbol)
            if isinstance(instrument_id, Err):
                return instrument_id
            self._console.locked()
            outcome = self._close_positions(signal.symbol, instrument_id.value)
        else:
            quantity = self._quantity(signal.sizing)
            if isinstance(quantity, Err):
                return quantity
            instrument_id = self._listed_instrument(signal.symbol)
            if isinstance(instrument_id, Err):
                return instrument_id
            self._console.locked()
            outcome = self._replace_position(signal, instrument_id.value, quantity.value)
        if isinstance(outcome, Err):
            return outcome
        self._console.unlocked()
        return outcome

    def _quantity(self, sizing: LotSizing) -> Result[float, BrokerFailure | Refusal]:
        balance = self._broker.account_balance()
        if isinstance(balance, Err):
            return balance
        if balance.value is None:
            return Err(NoBalance())
        return sizing.quantity_for(balance.value)

    def _listed_instrument(self, symbol: str) -> Result[int, BrokerFailure | Refusal]:
        instrument_id = self._broker.instrument_id(symbol)
        if isinstance(instrument_id, Err):
            return instrument_id
        if instrument_id.value is None:
            return Err(UnknownSymbol(symbol))
        return Ok(instrument_id.value)

    def _replace_position(self, signal: OpenSignal, instrument_id: int, quantity: float) -> Result[None, BrokerFailure]:
        closed = self._close_positions(signal.symbol, instrument_id)
        if isinstance(closed, Err):
            return closed
        return self._place_order(instrument_id, quantity, signal.side, signal.stop_loss, signal.take_profit)

    def _close_positions(self, symbol: str, instrument_id: int) -> Result[None, BrokerFailure]:
        while True:
            rows = self._broker.open_position_count(instrument_id)
            if isinstance(rows, Err):
                return rows
            if not rows.value:
                return Ok(None)
            for _ in range(rows.value):
                closed = self._broker.request_close(instrument_id)
                if isinstance(closed, Err):
                    return closed
                self._console.closing(symbol)

    def _place_order(
        self, instrument_id: int, quantity: float, side: Side, stop_loss: int, take_profit: int
    ) -> Result[None, BrokerFailure]:
        while True:
            order_id = self._broker.place_market_order(
                instrument_id, quantity, side, stop_loss=stop_loss, take_profit=take_profit
            )
            if isinstance(order_id, Err):
                return order_id
            if order_id.value:
                self._console.order_placed(order_id.value)
                return Ok(None)
            self._console.order_retry(side)
