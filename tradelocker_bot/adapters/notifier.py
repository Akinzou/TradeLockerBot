"""Hands the operator's alerts to a chat without making a signal wait for
it (ADR 0027).

The console calls ``notify`` inside the lock every signal shares, so a slow
or unreachable chat must cost the trading path nothing: ``notify`` only
queues, and one thread of the notifier's own sends, in order, trying a
message again while the chat may get over the failure. Every message it
cannot send is reported to the log, by the words it starts with: the line
itself is already there, printed by the console.
"""

import collections
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tradelocker_bot.adapters.ascii_alerts import print_red
from tradelocker_bot.application.ports import Clock
from tradelocker_bot.domain.result import Err, Result

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

# Far above what a burst of alerts queues while the chat answers; a flood
# beyond it is dropped and reported rather than held in memory.
CAPACITY = 100

# The words a report names a message by; every line the bot sends starts
# with a few words and a colon.
NAMED_CHARACTERS = 40


@dataclass(frozen=True)
class SendFailure:
    """Why a message was not sent, and whether the same request may yet
    succeed: a refused one, for a wrong chat or a blocked bot, would not.
    ``retry_after`` is the chat's own wait, as it gave it; the notifier
    decides which waits it keeps."""

    reason: str
    retry: bool
    retry_after: float | None = None


class Chat(Protocol):
    """The port to the operator's chat, a process boundary the notifier
    crosses; ``TelegramChat`` is its adapter. Here rather than among the
    use case's ports, because only adapters hand it text."""

    def send(self, text: str) -> Result[None, SendFailure]:
        ...


# The log line for a message not sent: red, as the lines it was for, and
# never itself sent, so a chat outage cannot feed on itself.
print_report = print_red


def _name(text: str) -> str:
    return text.partition(":")[0][:NAMED_CHARACTERS]


def _wait(failure: SendFailure, attempt: int) -> float:
    asked = failure.retry_after
    # Only a wait a server can mean: math.isfinite also turns away the NaN
    # and Infinity that JSON readers accept.
    if asked is None or not math.isfinite(asked) or asked < 0:
        return WAITS_SECONDS[attempt - 1]
    return min(asked, MAX_WAIT_SECONDS)


class Delivery:
    """Sends one message, trying it again on a failure the chat may get
    over, and reports it when it is not sent."""

    def __init__(self, chat: Chat, clock: Clock, report: Callable[[str], None]):
        self._chat = chat
        self._clock = clock
        self._report = report

    def __call__(self, text: str, logged_at: float) -> None:
        for attempt in range(1, ATTEMPTS + 1):
            sent = self._chat.send(self._dated(text, logged_at))
            if not isinstance(sent, Err):
                return
            failure = sent.error
            if not failure.retry:
                self._report(f'Telegram: the "{_name(text)}" message was not sent: {failure.reason}')
                return
            if attempt < ATTEMPTS:
                self._clock.sleep(_wait(failure, attempt))
        self._report(f'Telegram: the "{_name(text)}" message was not sent after {ATTEMPTS} tries: {failure.reason}')

    def _dated(self, text: str, logged_at: float) -> str:
        late = self._clock.now() - logged_at
        if late < LATE_SECONDS:
            return text
        # First, so the cut to the chat's longest message never takes it.
        return f"(sent {int(late)} seconds after the bot logged it)\n{text}"


class BackgroundNotifier:
    """Queues each message for one thread that delivers them in order.

    A daemon thread, so a chat that does not answer cannot keep the bot
    from stopping; ``stop`` gives the queue the seconds ``end`` set aside,
    then reports what is left.

    One condition guards everything: the waiting messages, the one being
    sent and the counts. A queue with a lock of its own beside it was two
    states to keep in step, and the gaps between them lost messages from
    the count.
    """

    def __init__(self, deliver: Callable[[str, float], None], clock: Clock, report: Callable[[str], None],
                 capacity: int = CAPACITY):
        self._deliver = deliver
        self._clock = clock
        self._report = report
        self._capacity = capacity
        self._state = threading.Condition()
        # Each entry carries how many dropped messages it reports, 0 for the
        # bot's own lines, rather than the stop telling a count by its text:
        # the stop then reports a waiting count as a count, not as a line
        # the log would have.
        self._waiting = collections.deque()
        self._sending = None
        # Apart from the counts already queued, so a drop is reported once:
        # by the queued count or by this one, never by both or neither.
        self._dropped = 0
        self._deadline = None

    def start(self) -> None:
        threading.Thread(target=self._run, name="telegram-notifier", daemon=True).start()

    def notify(self, text: str) -> None:
        with self._state:
            queued = self._queue(text, reports=0)
            if not queued:
                self._dropped += 1
        if not queued:
            self._report(f'Telegram: the "{_name(text)}" message was not sent: '
                         f"the queue of {self._capacity} was full")

    def end(self, seconds: float) -> None:
        """Sets aside ``seconds`` from now, the bot's end, for ``stop``: not
        from when Python gets to its exit functions, after waiting for the
        webhook's threads."""
        with self._state:
            self._deadline = self._clock.now() + seconds

    def stop(self) -> None:
        """Waits, until the time ``end`` set aside runs out, for every
        message to be handled, then reports the bot's own lines still
        pending, which the stop loses, and the dropped messages the chat
        has not heard of."""
        with self._state:
            left = 0.0 if self._deadline is None else max(self._deadline - self._clock.now(), 0.0)
            self._state.wait_for(lambda: not self._waiting and self._sending is None, left)
            pending = [*self._waiting, *([self._sending] if self._sending else [])]
            lines = sum(1 for _, _, reports in pending if not reports)
            dropped = self._dropped + sum(reports for _, _, reports in pending)
            self._dropped = 0
        if lines:
            self._report(f"Telegram: the bot stopped with {lines} of its messages not sent; the log has them")
        if dropped:
            self._report(f"Telegram: the queue was full and dropped {dropped} of the bot's messages; "
                         "the log has them")

    def _queue(self, text: str, reports: int) -> bool:
        # The caller holds the condition, so the room check, the append and
        # whatever count the caller keeps are one step for every thread.
        if len(self._waiting) >= self._capacity:
            return False
        self._waiting.append((text, self._clock.now(), reports))
        self._state.notify_all()
        return True

    def _run(self) -> None:
        while True:
            with self._state:
                self._state.wait_for(lambda: self._waiting)
                self._sending = self._waiting.popleft()
            text, logged_at, _ = self._sending
            # Any exception, so one message's failure cannot end the thread
            # and silence every message after it. By type alone: its text
            # could hold the request, and the token in it.
            try:
                self._deliver(text, logged_at)
            except Exception as error:
                self._report(f'Telegram: the "{_name(text)}" message was not sent: '
                             f"an error in the bot ({type(error).__name__})")
            with self._state:
                self._sending = None
                self._queue_dropped_count()
                self._state.notify_all()

    def _queue_dropped_count(self) -> None:
        # Once the queue is empty, the phone hears that messages were lost,
        # not only the log: a flood of rejections may have pushed out the one
        # that needed action. Not while lines wait: in a flood the count
        # would take every slot that frees up, ahead of the lines themselves.
        # An empty queue always has room for it.
        if self._dropped and not self._waiting:
            text = f"Telegram: the queue was full and dropped {self._dropped} of the bot's messages; the log has them"
            self._queue(text, reports=self._dropped)
            self._dropped = 0
