from dataclasses import dataclass

from tradelocker_bot.application.ports import Broker, BrokerFailure, OperatorConsole
from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.order_side import order_side
from tradelocker_bot.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class TradeSignal:
    """One webhook alert, field by field, as the legacy handler read it.

    Unvalidated on purpose: validation into domain values is roadmap step 3.
    """

    symbol: str
    direction: str
    lot: str
    take_profit: int
    stop_loss: int
    action: str
    invert: str


class ExecuteSignal:
    """Close and open positions for one signal, in the legacy order (ADR 0005).

    Every step is kept, including the ones known to be wrong (the instrument
    looked up twice, the side resolved only after positions were closed), so
    this move changes no broker call; fixing them is a declared behaviour step.
    """

    def __init__(self, broker: Broker, console: OperatorConsole):
        self._broker = broker
        self._console = console

    def execute(self, signal: TradeSignal) -> Result[None, BrokerFailure]:
        """``Ok(None)`` once handled, or the first broker failure, returned at
        once without ``unlocked`` (ADR 0006).

        Lot and inversion errors still raise: they are input validation, which
        roadmap step 3 moves ahead of every broker call as its own Result.
        """
        balance = self._broker.account_balance()
        if isinstance(balance, Err):
            return balance
        quantity = LotSizing.parse(signal.lot).quantity_for(balance.value)
        self._console.locked()
        if signal.action == "close":
            outcome = self._close_positions(signal.symbol)
        elif signal.action == "open":
            outcome = self._replace_position(signal, quantity)
        else:
            outcome = Ok(None)
        if isinstance(outcome, Err):
            return outcome
        self._console.unlocked()
        return outcome

    def _replace_position(self, signal: TradeSignal, quantity: float) -> Result[None, BrokerFailure]:
        closed = self._close_positions(signal.symbol)
        if isinstance(closed, Err):
            return closed
        instrument_id = self._broker.instrument_id(signal.symbol)
        if isinstance(instrument_id, Err):
            return instrument_id
        side = order_side(signal.direction, signal.invert)
        return self._place_order(instrument_id.value, quantity, side, signal.stop_loss, signal.take_profit)

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
        self, instrument_id: int, quantity: float, side: str, stop_loss: int, take_profit: int
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
