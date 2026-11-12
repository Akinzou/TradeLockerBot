"""Runs the webhook's lines as one signal and ends the way the caller expects
(ADR 0010).

The use case returns every outcome as a value; this is where each one is
turned into what the webhook thread does today: one operator line for a
rejection or a refusal, the client's own exception for a broker failure, and
nothing more for an order the broker rejected, which the use case reports.
A broker failure, and any other exception that ends a valid signal, also
gets a red line before it is raised (ADR 0027).
"""

from contextlib import AbstractContextManager

from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.application.execute_signal import ExecuteSignal
from tradelocker_bot.application.ports import BrokerFailure, OrderRejected
from tradelocker_bot.domain.result import Err
from tradelocker_bot.domain.signal import parse_signal


class SignalHandler:
    """One handler for every request, holding the lock they all share.

    The lock is passed in rather than made here, so the composition root
    owns the one critical section every signal goes through.
    """

    def __init__(self, execute_signal: ExecuteSignal, console: PrintingConsole, lock: AbstractContextManager):
        self._execute_signal = execute_signal
        self._console = console
        self._lock = lock

    def handle(self, lines: list[str]) -> None:
        signal = parse_signal(lines)
        if isinstance(signal, Err):
            # Refused before the lock, so an invalid alert neither waits behind
            # nor delays a valid one, and before any broker call; the thread
            # ends without an exception, because the operator line says it all
            # (ADR 0008).
            self._console.rejected(signal.error)
            return
        symbol = signal.value.symbol
        with self._lock:
            # Any other exception, a bug for one, ends the thread as before,
            # but named first in a red line too: a traceback alone says
            # nothing to the operator's phone, and the signal may have
            # stopped after the close (ADR 0027).
            try:
                unanswered = self._execute(signal.value)
            except Exception as error:
                self._console.bot_failed(symbol, error)
                raise
            if unanswered is not None:
                # The client's own exception object, raised inside the lock:
                # the webhook thread fails with the same type, message and
                # attributes as before the Result (ADR 0006). Kept raising:
                # no answer may still mean a placed order.
                self._console.broker_failed(symbol, unanswered)
                raise unanswered

    def _execute(self, signal) -> Exception | None:
        """The client's exception when a broker call got no answer; ``None``
        once every other outcome is reported."""
        result = self._execute_signal.execute(signal)
        if not isinstance(result, Err):
            return None
        if isinstance(result.error, BrokerFailure):
            return result.error.cause
        if isinstance(result.error, OrderRejected):
            # Not raised: the broker answered, the use case reported it with
            # the account's state, and a traceback would bury that line.
            # Still an `Err`, so a later caller, such as a webhook answer, can
            # tell a rejected order from a placed one (ADR 0021).
            return None
        # The broker answered and ruled the signal out before any close
        # request: reported like a payload rejection, without an exception
        # (ADR 0009).
        self._console.rejected(result.error)
        return None
