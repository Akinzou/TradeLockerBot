def order_side(direction: str, invert: str) -> str:
    """The side to trade: ``direction`` as given, or reversed with ``Invert``.

    The direction is not validated, and ``Invert`` turns anything other than
    exactly ``buy`` into ``buy``. Both mirror the legacy handler, because this
    extraction must not change behaviour (ADR 0001); the characterization tests
    pin them as known defects, and strict directions arrive in roadmap step 3.
    """
    if invert == "NonInvert":
        return direction
    if invert == "Invert":
        return "sell" if direction == "buy" else "buy"
    raise ValueError("Invalid value for isInvert. Expected 'NonInvert' or 'Invert'.")
