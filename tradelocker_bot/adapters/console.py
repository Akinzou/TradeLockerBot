from collections.abc import Callable

from tradelocker_bot.adapters import ascii_alerts
from tradelocker_bot.adapters.shown import SHOWN_REASON_CHARACTERS, shown
from tradelocker_bot.application.refusal import NoBalance, Refusal, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import UnusableQuantity
from tradelocker_bot.domain.signal import InvalidSignal, Side


def _why(reason: InvalidSignal | Refusal) -> str:
    # One shape for every reason, "<what> is <found>, expected <what fits>",
    # so the operator reads a payload error and a broker-side refusal alike.
    if isinstance(reason, InvalidSignal):
        found = "missing" if reason.value is None else shown(reason.value)
        return f"line {reason.line} ({reason.field}) is {found}, expected {reason.expected}"
    if isinstance(reason, UnknownSymbol):
        return f"line 1 (symbol) is {shown(reason.symbol)}, expected an instrument the broker lists"
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

    Each red line, one the operator has to act on, is also handed to
    ``notify`` as its text without colours (ADR 0027). Here rather than in a
    second console wrapped around this one: the red lines are written here,
    and a wrapper would have to forward every other line and build these
    again, so one wording could drift from the other.
    """

    def __init__(self, notify: Callable[[str], None]):
        self._notify = notify

    def _alert(self, text: str) -> None:
        ascii_alerts.print_red(text)
        self._notify(text)

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
        self._alert(f"Still closing: {listed} {int(seconds)} seconds after the first close request; "
                    f"later signals wait until {closes}, check {them} in TradeLocker")

    def closed(self, symbol: str, seconds: float) -> None:
        """The end of a close that logged ``still_closing`` (ADR 0022).

        Handed on like a red line, though it asks nothing of the operator:
        the chat that was told later signals wait has to learn that the wait
        is over. Green for that reason, and no word on what comes next, since
        an open signal's order still follows and has lines of its own.
        """
        text = f"Closed after {int(seconds)} seconds: the broker lists no open {symbol} position"
        ascii_alerts.print_green(text)
        self._notify(text)

    def unlocked(self) -> None:
        print("Normal: Unlocked")

    def rejected(self, reason: InvalidSignal | Refusal) -> None:
        """Why a signal was refused: before any broker call (ADR 0008), or
        once the broker answered, before any close request (ADR 0009).

        Not part of the ``OperatorConsole`` port: the use case returns a
        refusal rather than printing it, so the inbound side decides how to
        report it; today one console line, later the webhook response too.
        """
        self._alert(f"Signal rejected: {_why(reason)}")

    def order_rejected(self, symbol: str, side: Side, reason: str | None, open_positions: int | None) -> None:
        """An order the broker answered without creating, and what the broker
        lists on the symbol afterwards (ADR 0021).

        Not "Signal rejected": the close before it was carried out. The line
        ends with the account's state, from a count made after the rejection,
        because the operator reads it to decide whether to act.
        """
        why = "no reason given" if reason is None else shown(reason, SHOWN_REASON_CHARACTERS)
        self._alert(f"Order rejected: the broker refused to {side.value} {symbol} ({why}); "
                    f"{_left_open(symbol, open_positions)}")

    def broker_failed(self, symbol: str, cause: Exception) -> None:
        """A broker call for the signal on ``symbol`` that got no answer,
        which stopped the signal there (ADR 0027).

        Not part of the ``OperatorConsole`` port, like ``rejected``: the use
        case returns the failure, and the inbound side raises it. The
        exception's type alone, not its text: the client's can hold a token
        or the server's whole answer (ADR 0025), and this line also leaves
        the host. The traceback after it still has the text, in the log.
        """
        self._alert(f"Broker failed: a call for {symbol} got no answer ({type(cause).__name__}); "
                    f"the signal stopped there, check {symbol} in TradeLocker")

    def bot_failed(self, symbol: str, error: Exception) -> None:
        """Any other exception that ended the signal on ``symbol``, a bug for
        one: by its type alone, as for ``broker_failed``, and with the same
        advice, since the signal may have stopped after the close."""
        self._alert(f"Bot failed: an error in the bot ({type(error).__name__}) while handling {symbol}; "
                    f"the signal stopped there, check {symbol} in TradeLocker")
