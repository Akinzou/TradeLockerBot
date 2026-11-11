"""What the execute-signal use case needs from the outside world (ADR 0005).

Ports raise the client's own exceptions for now; a Result at the boundary is
roadmap step 4b.
"""

from typing import Protocol


class Broker(Protocol):
    def account_balance(self) -> float | None:
        """The account's projected balance exactly as the broker reports it.

        Returned uncoerced, possibly ``None``: the use case must fail where the
        legacy handler failed, at lot sizing, not earlier.
        """

    def instrument_id(self, symbol: str) -> int:
        ...

    def open_position_count(self, instrument_id: int) -> int:
        """How many position rows the broker lists for the instrument.

        Provisional (ADR 0005): together with ``request_close`` it mirrors the
        legacy one-request-per-row close loop, which roadmap step 6 replaces.
        """

    def request_close(self, instrument_id: int) -> None:
        """Ask the broker to close the instrument's positions; it may fill later."""

    def place_market_order(
        self, instrument_id: int, quantity: float, side: str, stop_loss: int, take_profit: int
    ) -> int | None:
        """Order id, or ``None`` when the broker returned none."""


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
