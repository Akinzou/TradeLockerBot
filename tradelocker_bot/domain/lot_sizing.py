import math
from dataclasses import dataclass

from tradelocker_bot.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class UnusableQuantity:
    """A sizing that is valid on its own but gives, for this balance, a
    quantity no broker can trade (ADR 0009)."""

    balance: float
    quantity: float

    @property
    def balance_is_usable(self) -> bool:
        """False when the balance, not the lot, rules the quantity out: no
        lot sizes a position from a balance that is not above zero."""
        return math.isfinite(self.balance) and self.balance > 0


@dataclass(frozen=True)
class LotSizing:
    """Position size that grows with the account: ``base_lot`` per ``balance_step``.

    Both numbers must be positive and finite (ADR 0008). The rule lives in the
    constructor, so no code path can build a sizing that is zero, negative,
    infinite or NaN; ``parse`` relies on it rather than repeating it.

    The quantity can still be unusable for a given balance: zero when the
    balance is too small for it to round above zero, negative when the
    balance is, infinite when the product overflows (``1e306/1``). That needs
    the broker's balance, so ``quantity_for`` refuses it rather than the
    constructor (ADR 0009).
    """

    base_lot: float
    balance_step: float

    def __post_init__(self):
        if not all(math.isfinite(n) and n > 0 for n in (self.base_lot, self.balance_step)):
            raise ValueError(f"lot sizing needs two positive finite numbers, got {self.base_lot}/{self.balance_step}")

    @classmethod
    def parse(cls, text: str) -> "LotSizing | None":
        """The sizing ``<lot>/<balance step>`` describes, or ``None`` if it
        describes none. Spaces around each number are accepted, as before."""
        parts = text.split("/")
        if len(parts) != 2:
            return None
        try:
            return cls(*map(float, parts))
        except ValueError:
            return None

    def quantity_for(self, balance: float) -> Result[float, UnusableQuantity]:
        """Lots for this balance, rounded to two decimals as before, or why
        there is none: anything but a finite number above zero.

        Checked after rounding, because the rounded number is what the broker
        would receive.
        """
        quantity = round((balance / self.balance_step) * self.base_lot, 2)
        if math.isfinite(quantity) and quantity > 0:
            return Ok(quantity)
        return Err(UnusableQuantity(balance=balance, quantity=quantity))
