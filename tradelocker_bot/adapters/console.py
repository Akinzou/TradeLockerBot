from libs import AsciiAlerts


class PrintingConsole:
    """The ``OperatorConsole`` port as the legacy stdout lines (ADR 0005).

    Kept as ``print`` with the legacy colours and reset lines rather than a
    logger, because the operator reads this output and a logger would change
    its format; that is a behaviour step, not this move.
    """

    def locked(self) -> None:
        print("Normal: Locked")

    def closing(self, symbol: str) -> None:
        print(f"Closing: {symbol}")

    def order_retry(self, side: str) -> None:
        print(AsciiAlerts.RED + f"{side.capitalize()} order was not successful, trying again...")
        AsciiAlerts.resetStyle()

    def order_placed(self, order_id: object) -> None:
        print(AsciiAlerts.GREEN + f"Order placed successfully, order ID: {order_id}")
        AsciiAlerts.resetStyle()

    def unlocked(self) -> None:
        print("Normal: Unlocked")
