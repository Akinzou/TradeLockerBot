"""Why a valid signal is not traded once the broker has answered (ADR 0009).

Separate from ``InvalidSignal``: these are not errors in the payload alone,
since the same signal trades on another account or at another balance, and a
missing balance is not a payload line at all. Separate from ``BrokerFailure``
too: the broker did answer, so there is nothing to retry or re-raise, only a
signal to refuse.
"""

from dataclasses import dataclass
from typing import Union

from tradelocker_bot.domain.lot_sizing import UnusableQuantity


@dataclass(frozen=True)
class NoBalance:
    """The account state carries no number to size the position from."""


@dataclass(frozen=True)
class UnknownSymbol:
    """The broker lists no instrument with exactly this name."""

    symbol: str


Refusal = Union[NoBalance, UnknownSymbol, UnusableQuantity]
