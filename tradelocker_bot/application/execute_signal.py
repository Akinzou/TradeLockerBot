from tradelocker_bot.application.ports import Broker, BrokerFailure, OperatorConsole, OrderRejected
from tradelocker_bot.application.refusal import NoBalance, Refusal, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.result import Err, Ok, Result
from tradelocker_bot.domain.signal import CloseSignal, OpenSignal, Signal


class ExecuteSignal:
    """Close and open positions for one valid signal (ADR 0005, ADR 0008,
    ADR 0009).

    The signal is parsed before it gets here, so every payload error is
    already refused without a broker call. What only the broker can rule out,
    a missing balance, an unusable quantity, an unknown symbol, is refused
    here before the ``locked`` line and before any close request, so a
    refused signal never leaves the account flat. An order the broker itself
    rejects, below its minimum lot for one, still does, since the close comes
    first; it is placed once, reported with a fresh count of the
    positions left, and returned as ``OrderRejected`` (ADR 0021).
    """

    def __init__(self, broker: Broker, console: OperatorConsole):
        self._broker = broker
        self._console = console

    def execute(self, signal: Signal) -> Result[None, BrokerFailure | Refusal | OrderRejected]:
        """``Ok(None)`` once handled; otherwise the refusal or the first broker
        failure, returned at once without ``unlocked`` (ADR 0006), or the
        order's rejection, returned once it is reported, after ``unlocked``
        (ADR 0021).

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
        # A rejected order is reported here, between the Locked and Unlocked
        # lines, and its handling ends there; any other `Err` leaves at once.
        if isinstance(outcome, Err) and not isinstance(outcome.error, OrderRejected):
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

    def _replace_position(
        self, signal: OpenSignal, instrument_id: int, quantity: float
    ) -> Result[None, BrokerFailure | OrderRejected]:
        closed = self._close_positions(signal.symbol, instrument_id)
        if isinstance(closed, Err):
            return closed
        return self._place_order(signal, instrument_id, quantity)

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
        self, signal: OpenSignal, instrument_id: int, quantity: float
    ) -> Result[None, BrokerFailure | OrderRejected]:
        # Once, not until an id comes back: the same order again would get
        # the same answer, and a loop with no end would hold the lock that
        # every later signal waits for (ADR 0021).
        order_id = self._broker.place_market_order(
            instrument_id, quantity, signal.side, stop_loss=signal.stop_loss, take_profit=signal.take_profit
        )
        if isinstance(order_id, Err) and isinstance(order_id.error, OrderRejected):
            return self._report_rejection(signal, instrument_id, order_id.error)
        if isinstance(order_id, Err):
            return order_id
        self._console.order_placed(order_id.value)
        return Ok(None)

    def _report_rejection(
        self, signal: OpenSignal, instrument_id: int, rejection: OrderRejected
    ) -> Result[None, BrokerFailure | OrderRejected]:
        # Counted again rather than taken as zero from the close loop: the
        # client resends an order whose answer was lost, so a rejection can
        # follow a fill, and a position can be opened by hand meanwhile. The
        # operator acts on what this line says the account holds.
        rows = self._broker.open_position_count(instrument_id)
        open_positions = None if isinstance(rows, Err) else rows.value
        self._console.order_rejected(signal.symbol, signal.side, rejection.reason, open_positions)
        if isinstance(rows, Err):
            return rows
        return Err(rejection)
