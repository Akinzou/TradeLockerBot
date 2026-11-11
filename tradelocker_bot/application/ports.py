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

        Provisional (ADR 0005): together with ``request_close`` it mirrors the
        legacy one-request-per-row close loop, which roadmap step 6 replaces.
        """

    def request_close(self, instrument_id: int) -> Result[None, BrokerFailure]:
        """Ask the broker to close the instrument's positions; it may fill later."""

    def place_market_order(
        self, instrument_id: int, quantity: float, side: Side, stop_loss: int, take_profit: int
    ) -> Result[int | None, BrokerFailure]:
        """Order id, or ``Ok(None)`` when the broker answered without one."""


class OperatorConsole(Protocol):
    def locked(self) -> None:
        ...

    def closing(self, symbol: str) -> None:
        ...

    def order_retry(self, side: Side) -> None:
        ...

    def order_placed(self, order_id: int) -> None:
        ...

    def unlocked(self) -> None:
        ...
