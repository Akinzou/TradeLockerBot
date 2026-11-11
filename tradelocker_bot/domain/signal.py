"""A webhook alert parsed into what it asks for, or the first line that stops
it, before any broker call (ADR 0008).

The payload is the frozen seven-line format: symbol, direction, lot, take
profit, stop loss, action, inversion. ``close`` reads only the symbol and the
action, so junk in a line it never uses cannot keep a position open. The
inversion is resolved here, into the side to trade, so an invalid flag can no
longer stop an ``open`` after its positions were already closed.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Sequence, Union

from tradelocker_bot.domain.lot_sizing import LotSizing
from tradelocker_bot.domain.result import Err, Ok, Result


class Side(Enum):
    BUY = "buy"
    SELL = "sell"

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True)
class OpenSignal:
    """Replace the instrument's positions with one market order."""

    symbol: str
    side: Side
    sizing: LotSizing
    take_profit: int
    stop_loss: int


@dataclass(frozen=True)
class CloseSignal:
    """Close every position on the instrument."""

    symbol: str


Signal = Union[OpenSignal, CloseSignal]


@dataclass(frozen=True)
class InvalidSignal:
    """The first line that stops a signal: its 1-based number, what it holds
    (``None`` when the payload ends before it) and what it should hold.

    ``value`` is the webhook's text, unescaped; whoever shows it must make it
    safe to print.
    """

    line: int
    field: str
    value: Optional[str]
    expected: str


@dataclass(frozen=True)
class _Field:
    line: int
    name: str
    expected: str
    parse: Callable[[str], Any]  # the value, or None when the text is not one


def _word(text: str) -> str:
    # The owner's decision (ADR 0008): case and surrounding spaces do not change
    # what a direction or an action means. The inversion flag stays exact.
    return text.strip().lower()


def _symbol(text: str) -> Optional[str]:
    # Kept verbatim: only the broker knows its instrument names (ADR 0009).
    return text if text.strip() else None


def _whole_number(text: str) -> Optional[int]:
    # int() as before: surrounding spaces, a sign and zero stay accepted.
    try:
        return int(text)
    except ValueError:
        return None


_DIRECTIONS = {"buy": Side.BUY, "sell": Side.SELL}
_ACTIONS = {"open": "open", "close": "close"}
_INVERSIONS = {"Invert": True, "NonInvert": False}

SYMBOL = _Field(1, "symbol", "an instrument name", _symbol)
DIRECTION = _Field(2, "direction", "buy or sell", lambda text: _DIRECTIONS.get(_word(text)))
LOT = _Field(3, "lot", "<lot>/<balance step>, two positive numbers", LotSizing.parse)
TAKE_PROFIT = _Field(4, "take profit", "a whole number", _whole_number)
STOP_LOSS = _Field(5, "stop loss", "a whole number", _whole_number)
ACTION = _Field(6, "action", "open or close", lambda text: _ACTIONS.get(_word(text)))
INVERSION = _Field(7, "inversion", "Invert or NonInvert", _INVERSIONS.get)


def _read(lines: Sequence[str], fields: Sequence[_Field]) -> Result[list, InvalidSignal]:
    values = []
    for field in fields:
        text = lines[field.line - 1] if len(lines) >= field.line else None
        value = None if text is None else field.parse(text)
        if value is None:
            return Err(InvalidSignal(field.line, field.name, text, field.expected))
        values.append(value)
    return Ok(values)


def parse_signal(lines: Sequence[str]) -> Result[Signal, InvalidSignal]:
    """The signal the payload asks for, or the first line that stops it.

    The symbol and the action are read first, because the action decides which
    other lines count; ``open`` then reads lines 2 to 5 and 7 in order. Lines
    after the seventh are ignored, as before.
    """
    head = _read(lines, (SYMBOL, ACTION))
    if isinstance(head, Err):
        return head
    symbol, action = head.value
    if action == "close":
        return Ok(CloseSignal(symbol))
    rest = _read(lines, (DIRECTION, LOT, TAKE_PROFIT, STOP_LOSS, INVERSION))
    if isinstance(rest, Err):
        return rest
    direction, sizing, take_profit, stop_loss, inverted = rest.value
    side = direction.opposite() if inverted else direction
    return Ok(OpenSignal(symbol, side, sizing, take_profit, stop_loss))
