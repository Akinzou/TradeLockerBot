from dataclasses import dataclass

from tradelocker_bot.application.ports import Broker, OperatorConsole
from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.order_side import order_side


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

    def execute(self, signal: TradeSignal) -> None:
        balance = self._broker.account_balance()
        quantity = LotSizing.parse(signal.lot).quantity_for(balance)
        self._console.locked()
        if signal.action == "close":
            self._close_positions(signal.symbol)
        if signal.action == "open":
            self._close_positions(signal.symbol)
            instrument_id = self._broker.instrument_id(signal.symbol)
            side = order_side(signal.direction, signal.invert)
            self._place_order(instrument_id, quantity, side, signal)
        self._console.unlocked()

    def _close_positions(self, symbol: str) -> None:
        instrument_id = self._broker.instrument_id(symbol)
        rows = self._broker.open_position_count(instrument_id)
        while rows:
            for _ in range(rows):
                self._broker.request_close(instrument_id)
                self._console.closing(symbol)
            rows = self._broker.open_position_count(instrument_id)

    def _place_order(self, instrument_id: int, quantity: float, side: str, signal: TradeSignal) -> None:
        order_id = None
        while not order_id:
            order_id = self._broker.place_market_order(
                instrument_id, quantity, side, stop_loss=signal.stop_loss, take_profit=signal.take_profit
            )
            if order_id:
                self._console.order_placed(order_id)
            else:
                self._console.order_retry(side)
