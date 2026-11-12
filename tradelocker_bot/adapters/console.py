from tradelocker_bot.adapters import ascii_alerts
from tradelocker_bot.application.refusal import NoBalance, Refusal, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import UnusableQuantity
from tradelocker_bot.domain.signal import InvalidSignal, Side

# Enough to recognise a mistyped field; a longer value is cut, so a hostile
# payload cannot flood the log with one line.
SHOWN_CHARACTERS = 40


# A broker's reason is a sentence rather than a field, so it is cut later;
# still cut, since the text is the broker's, not the bot's.
SHOWN_REASON_CHARACTERS = 160


def _shown(value: str, limit: int = SHOWN_CHARACTERS) -> str:
    # repr, not the raw text: the value comes from the webhook or the broker,
    # and its control characters (ESC, CR) could otherwise colour or forge
    # operator lines.
    if len(value) <= limit:
        return repr(value)
    return f"{value[:limit]!r}... ({len(value)} characters)"


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


def _listed(symbol: str, open_positions: int) -> tuple[str, str]:
    # One wording for every line that names open positions, so an
    # `Order rejected:` and a `Still closing:` line read alike.
    if open_positions == 1:
        return f"the broker lists 1 open {symbol} position", "it"
    return f"the broker lists {open_positions} open {symbol} positions", "them"


def _left_open(symbol: str, open_positions: int | None) -> str:
    if open_positions is None:
        return f"the position count got no answer, check {symbol} in TradeLocker"
    if open_positions == 0:
        return f"no {symbol} position is open"
    listed, them = _listed(symbol, open_positions)
    return f"{listed}, check {them} in TradeLocker"


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

    def order_placed(self, order_id: int) -> None:
        print(ascii_alerts.GREEN + f"Order placed successfully, order ID: {order_id}")
        ascii_alerts.reset_style()

    def still_closing(self, symbol: str, open_positions: int, seconds: float) -> None:
        """A close the broker has not filled a minute after the first request
        (ADR 0022).

        Says that later signals wait, because the lock is held until the
        position closes, and a closed market can keep it shut for a weekend.
        """
        listed, them = _listed(symbol, open_positions)
        closes = "it closes" if open_positions == 1 else "they close"
        # One print with the reset inside, as for a rejected order: another
        # thread's rejection can print in between.
        print(f"{ascii_alerts.RED}Still closing: {listed} {int(seconds)} seconds after the first close request; "
              f"later signals wait until {closes}, check {them} in TradeLocker\n{ascii_alerts.RESET}")

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
        print(f"{ascii_alerts.RED}Signal rejected: {_why(reason)}\n{ascii_alerts.RESET}")

    def order_rejected(self, symbol: str, side: Side, reason: str | None, open_positions: int | None) -> None:
        """An order the broker answered without creating, and what the broker
        lists on the symbol afterwards (ADR 0021).

        Not "Signal rejected": the close before it was carried out. The line
        ends with the account's state, from a count made after the rejection,
        because the operator reads it to decide whether to act.
        """
        why = "no reason given" if reason is None else _shown(reason, SHOWN_REASON_CHARACTERS)
        # One print with the reset inside, rather than a reset line after: a
        # payload rejection from another thread can print in between, and it
        # must not inherit the red.
        print(f"{ascii_alerts.RED}Order rejected: the broker refused to {side.value} {symbol} ({why}); "
              f"{_left_open(symbol, open_positions)}\n{ascii_alerts.RESET}")
