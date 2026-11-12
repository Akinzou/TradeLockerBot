"""What the execute-signal use case needs from the outside world (ADR 0005).

Every broker call returns a ``Result`` (ADR 0006): a call that does not answer
is ``Err(BrokerFailure)``, never an exception. The console port returns
nothing; why it stays outside the Result is in the same ADR.
"""

from dataclasses import dataclass
from typing import Protocol

from tradelocker_bot.domain.result import Result
from tradelocker_bot.domain.signal import Side


@dataclass(frozen=True)
class BrokerFailure:
    """A broker call that did not answer, holding the client's own exception."""

    cause: Exception


@dataclass(frozen=True)
class OrderRejected:
    """The broker answered an order without creating it (ADR 0021).

    Not a ``BrokerFailure``: the broker did answer, so nothing is retried or
    re-raised. ``reason`` is the broker's own text, or ``None`` when it gave
    none.
    """

    reason: str | None


class Broker(Protocol):
    def account_balance(self) -> Result[float | None, BrokerFailure]:
        """The account's projected balance as the broker reports it, or
        ``Ok(None)`` when the answer holds no number (ADR 0009).

        Not coerced: a balance reported as text is not guessed at, it is
        missing, and the use case refuses the signal.
        """

    def instrument_id(self, symbol: str) -> Result[int | None, BrokerFailure]:
        """The id of the instrument with exactly this name, or ``Ok(None)``
        when the broker lists none (ADR 0009).

        ``Err`` only when the broker did not answer, so an outage can never
        pass for an unknown symbol.
        """

    def open_position_count(self, instrument_id: int) -> Result[int, BrokerFailure]:
        """How many position rows the broker lists for the instrument.

        The use case still asks for one close per row, as legacy did, though
        one request names the whole instrument: whether the broker closes
        every row on one request is not known (ADR 0022).
        """

    def request_close(self, instrument_id: int) -> Result[None, BrokerFailure]:
        """Ask the broker to close the instrument's positions; it may fill later."""

    def place_market_order(
        self, instrument_id: int, quantity: float, side: Side, stop_loss: int, take_profit: int
    ) -> Result[int, BrokerFailure | OrderRejected]:
        """The id of the order the broker created, or ``Err(OrderRejected)``
        when it answered without creating one (ADR 0021)."""


class Clock(Protocol):
    """The time the close loop paces itself by (ADR 0022)."""

    def now(self) -> float:
        """Seconds on a clock that never goes back; only a difference
        between two readings means anything."""

    def sleep(self, seconds: float) -> None:
        ...


class OperatorConsole(Protocol):
    def locked(self) -> None:
        ...

    def closing(self, symbol: str) -> None:
        ...

    def order_placed(self, order_id: int) -> None:
        ...

    def order_rejected(self, symbol: str, side: Side, reason: str | None, open_positions: int | None) -> None:
        """The broker's rejection and the positions it lists on the symbol
        afterwards; ``None`` when that count got no answer (ADR 0021)."""

    def still_closing(self, symbol: str, open_positions: int, seconds: float) -> None:
        """The positions still open ``seconds`` after the first close request
        (ADR 0022)."""

    def closed(self, symbol: str, seconds: float) -> None:
        """The broker lists no position ``seconds`` after the first close
        request, in a close that logged ``still_closing`` (ADR 0022)."""

    def unlocked(self) -> None:
        ...
