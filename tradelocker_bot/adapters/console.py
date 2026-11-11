from libs import AsciiAlerts
from tradelocker_bot.application.refusal import NoBalance, Refusal, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import UnusableQuantity
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


def _why(reason: InvalidSignal | Refusal) -> str:
    # One shape for every reason, "<what> is <found>, expected <what fits>",
    # so the operator reads a payload error and a broker-side refusal alike.
    if isinstance(reason, InvalidSignal):
        found = "missing" if reason.value is None else _shown(reason.value)
        return f"line {reason.line} ({reason.field}) is {found}, expected {reason.expected}"
    if isinstance(reason, UnknownSymbol):
        return f"line 1 (symbol) is {_shown(reason.symbol)}, expected an instrument the broker lists"
    if isinstance(reason, UnusableQuantity) and not reason.balance_is_usable:
        # Pointing at line 3 here would send the operator to fix an alert
        # that is fine.
        return f"the account balance is {reason.balance}, expected a positive number to size the position from"
    if isinstance(reason, UnusableQuantity):
        return (f"line 3 (lot) gives {reason.quantity} at a balance of {reason.balance}, "
                "expected a quantity above 0")
    if isinstance(reason, NoBalance):
        return "the account balance is missing or not a number, expected a number to size the position from"
    raise TypeError(f"no operator line for {reason!r}")


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

    def rejected(self, reason: InvalidSignal | Refusal) -> None:
        """Why a signal was refused: before any broker call (ADR 0008), or
        once the broker answered, before any close request (ADR 0009).

        Not part of the ``OperatorConsole`` port: the use case returns a
        refusal rather than printing it, so the inbound side decides how to
        report it; today one console line, later the webhook response too.
        """
        # One print with the reset inside, unlike the lines above: a payload
        # rejection is written outside the lock, so a thread printing in
        # between must not inherit the colour.
        print(f"{AsciiAlerts.RED}Signal rejected: {_why(reason)}\n{AsciiAlerts.RESET}")
