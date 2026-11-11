from libs import AsciiAlerts
from tradelocker_bot.domain.signal import InvalidSignal, Side

# Enough to recognise a mistyped field; a longer value is cut, so a hostile
# payload cannot flood the log with one line.
SHOWN_CHARACTERS = 40


def _shown(value: str) -> str:
    # repr, not the raw text: the value comes from the webhook, and its control
    # characters (ESC, CR) could otherwise colour or forge operator lines.
    if len(value) <= SHOWN_CHARACTERS:
        return repr(value)
    return f"{value[:SHOWN_CHARACTERS]!r}... ({len(value)} characters)"


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

    def order_retry(self, side: Side) -> None:
        print(AsciiAlerts.RED + f"{side.value.capitalize()} order was not successful, trying again...")
        AsciiAlerts.resetStyle()

    def order_placed(self, order_id: int) -> None:
        print(AsciiAlerts.GREEN + f"Order placed successfully, order ID: {order_id}")
        AsciiAlerts.resetStyle()

    def unlocked(self) -> None:
        print("Normal: Unlocked")

    def rejected(self, reason: InvalidSignal) -> None:
        """Why a signal was refused before any broker call (ADR 0008).

        Not part of the ``OperatorConsole`` port: the use case only ever
        receives a valid signal, so only the webhook side reports this.
        """
        found = "missing" if reason.value is None else _shown(reason.value)
        line = f"Signal rejected: line {reason.line} ({reason.field}) is {found}, expected {reason.expected}"
        # One print with the reset inside, unlike the lines above: this one is
        # written outside the lock, so a thread printing in between must not
        # inherit the colour.
        print(f"{AsciiAlerts.RED}{line}\n{AsciiAlerts.RESET}")
