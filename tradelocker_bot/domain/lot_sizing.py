import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LotSizing:
    """Position size that grows with the account: ``base_lot`` per ``balance_step``.

    Both numbers must be positive and finite (ADR 0008). The rule lives in the
    constructor, so no code path can build a sizing that is zero, negative,
    infinite or NaN; ``parse`` relies on it rather than repeating it.

    The quantity itself can still be unusable: zero when the balance is too
    small for it to round above zero, infinite when the product overflows
    (``1e306/1``). Both need the broker's balance, so roadmap step 3b refuses
    them.
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

    def quantity_for(self, balance: float) -> float:
        return round((balance / self.balance_step) * self.base_lot, 2)
