from dataclasses import dataclass


@dataclass(frozen=True)
class LotSizing:
    """Position size that grows with the account: ``base_lot`` per ``balance_step``.

    Invalid text raises instead of returning a Result. Nonsensical values
    (zero, negative, infinite, NaN) are accepted by ``parse``; a zero
    ``balance_step`` then raises ``ZeroDivisionError`` in ``quantity_for``. Both
    mirror the legacy handler exactly, because this extraction must not change
    behaviour (ADR 0001). The characterization tests pin these cases.
    Validation and a Result at the boundary arrive in roadmap step 3.
    """

    base_lot: float
    balance_step: float

    @classmethod
    def parse(cls, text: str) -> "LotSizing":
        base_lot, balance_step = map(float, text.split("/"))
        return cls(base_lot=base_lot, balance_step=balance_step)

    def quantity_for(self, balance: float) -> float:
        return round((balance / self.balance_step) * self.base_lot, 2)
