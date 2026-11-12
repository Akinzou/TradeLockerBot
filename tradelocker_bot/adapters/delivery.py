"""One message's tries at the operator's chat (ADR 0027).

Apart from the notifier's queue and thread: this decides how often and
how long to try one message, the notifier decides which message goes and
when the tries must stop.
"""

import math
from collections.abc import Callable

from tradelocker_bot.adapters.notifier import Chat, SendFailure, named
from tradelocker_bot.application.ports import Clock
from tradelocker_bot.domain.result import Err

ATTEMPTS = 3

# Between the tries, when the chat names no wait of its own: a dropped
# connection is usually back within seconds, a restarting server within
# tens of them.
WAITS_SECONDS = (2.0, 10.0)

# The chat's own wait is kept, since a try before it ends is refused too,
# up to this: a longer one, or a value no server means, would hold every
# later message for longer.
MAX_WAIT_SECONDS = 600.0

# A message sent this long after it was logged says so, so the operator
# does not act on a state that may have changed since.
LATE_SECONDS = 60.0


def _wait(failure: SendFailure, attempt: int) -> float:
    asked = failure.retry_after
    # Only a wait a server can mean: math.isfinite also turns away the NaN
    # and Infinity that JSON readers accept.
    if asked is None or not math.isfinite(asked) or asked < 0:
        return WAITS_SECONDS[attempt - 1]
    return min(asked, MAX_WAIT_SECONDS)


class Delivery:
    """Sends one message, trying it again on a failure the chat may get
    over, and returns the report of one it did not send.

    Returned rather than printed: the notifier decides, in one step with
    its stop, whether the stop has already counted the message, so each
    message gets one red line, never two.
    """

    def __init__(self, chat: Chat, clock: Clock):
        self._chat = chat
        self._clock = clock

    def __call__(self, text: str, logged_at: float, stopped: Callable[[], bool]) -> str | None:
        for attempt in range(1, ATTEMPTS + 1):
            # The notifier's stop has reported this message as not sent, so
            # a try after it could only make that report wrong.
            if stopped():
                return None
            sent = self._chat.send(self._dated(text, logged_at))
            if not isinstance(sent, Err):
                return None
            failure = sent.error
            if not failure.retry:
                return f'Telegram: the "{named(text)}" message was not sent: {failure.reason}'
            if attempt < ATTEMPTS:
                self._clock.sleep(_wait(failure, attempt))
        return f'Telegram: the "{named(text)}" message was not sent after {ATTEMPTS} tries: {failure.reason}'

    def _dated(self, text: str, logged_at: float) -> str:
        late = self._clock.now() - logged_at
        if late < LATE_SECONDS:
            return text
        # First, so the cut to the chat's longest message never takes it.
        return f"(sent {int(late)} seconds after the bot logged it)\n{text}"
