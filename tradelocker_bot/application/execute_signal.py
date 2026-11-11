from tradelocker_bot.application.ports import Broker, BrokerFailure, OperatorConsole
from tradelocker_bot.domain.result import Err, Ok, Result
from tradelocker_bot.domain.signal import CloseSignal, OpenSignal, Side, Signal


class ExecuteSignal:
    """Close and open positions for one valid signal (ADR 0005, ADR 0008).

    The signal is parsed before it gets here, so every input error is already
    refused without a broker call. The legacy order of broker calls is kept
    otherwise, including the instrument looked up twice on ``open``; fixing
    that is roadmap step 6.
    """

    def __init__(self, broker: Broker, console: OperatorConsole):
        self._broker = broker
        self._console = console

    def execute(self, signal: Signal) -> Result[None, BrokerFailure]:
        """``Ok(None)`` once handled, or the first broker failure, returned at
        once without ``unlocked`` (ADR 0006).

        ``close`` reads no balance: it sizes nothing (ADR 0008). A balance the
        broker reports without a value still raises from the lot sizing until
        roadmap step 3b.
        """
        if isinstance(signal, CloseSignal):
            self._console.locked()
            outcome = self._close_positions(signal.symbol)
        else:
            balance = self._broker.account_balance()
            if isinstance(balance, Err):
                return balance
            quantity = signal.sizing.quantity_for(balance.value)
            self._console.locked()
            outcome = self._replace_position(signal, quantity)
        if isinstance(outcome, Err):
            return outcome
        self._console.unlocked()
        return outcome

    def _replace_position(self, signal: OpenSignal, quantity: float) -> Result[None, BrokerFailure]:
        closed = self._close_positions(signal.symbol)
        if isinstance(closed, Err):
            return closed
        instrument_id = self._broker.instrument_id(signal.symbol)
        if isinstance(instrument_id, Err):
            return instrument_id
        return self._place_order(instrument_id.value, quantity, signal.side, signal.stop_loss, signal.take_profit)

    def _close_positions(self, symbol: str) -> Result[None, BrokerFailure]:
        instrument_id = self._broker.instrument_id(symbol)
        if isinstance(instrument_id, Err):
            return instrument_id
        while True:
            rows = self._broker.open_position_count(instrument_id.value)
            if isinstance(rows, Err):
                return rows
            if not rows.value:
                return Ok(None)
            for _ in range(rows.value):
                closed = self._broker.request_close(instrument_id.value)
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
