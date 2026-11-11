"""What the execute-signal use case needs from the outside world (ADR 0005).

Every broker call returns a ``Result`` (ADR 0006): a call that does not answer
is ``Err(BrokerFailure)``, never an exception. The console port returns
nothing; why it stays outside the Result is in the same ADR.
"""

from dataclasses import dataclass
from typing import Protocol

from tradelocker_bot.domain.result import Result


@dataclass(frozen=True)
class BrokerFailure:
    """A broker call that did not answer, holding the client's own exception."""

    cause: Exception


class Broker(Protocol):
    def account_balance(self) -> Result[float | None, BrokerFailure]:
        """The account's projected balance exactly as the broker reports it.

        Returned uncoerced, possibly ``None``: the use case must fail where the
        legacy handler failed, at lot sizing, not earlier.
        """

    def instrument_id(self, symbol: str) -> Result[int, BrokerFailure]:
        ...

    def open_position_count(self, instrument_id: int) -> Result[int, BrokerFailure]:
        """How many position rows the broker lists for the instrument.

        Provisional (ADR 0005): together with ``request_close`` it mirrors the
        legacy one-request-per-row close loop, which roadmap step 6 replaces.
        """

    def request_close(self, instrument_id: int) -> Result[None, BrokerFailure]:
        """Ask the broker to close the instrument's positions; it may fill later."""

    def place_market_order(
        self, instrument_id: int, quantity: float, side: str, stop_loss: int, take_profit: int
    ) -> Result[int | None, BrokerFailure]:
        """Order id, or ``Ok(None)`` when the broker answered without one."""


class OperatorConsole(Protocol):
    def locked(self) -> None:
        ...

    def closing(self, symbol: str) -> None:
        ...

    def order_retry(self, side: str) -> None:
        ...

    def order_placed(self, order_id: int) -> None:
        ...

    def unlocked(self) -> None:
        ...
