"""Hands the operator's alerts to a chat without making a signal wait for
it (ADR 0027).

The console calls ``notify`` inside the lock every signal shares, so a slow
or unreachable chat must cost the trading path nothing: ``notify`` only
queues, and one thread of the notifier's own sends, in order, trying a
message again while the chat may get over the failure. Every message it
cannot send is reported to the log, by the words it starts with: the line
itself is already there, printed by the console.
"""

import math
import queue
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
    succeed: a refused one, for a wrong chat or a blocked bot, would not."""

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
        return f"{text}\n(sent {int(late)} seconds after the bot logged it)"


class BackgroundNotifier:
    """Queues each message for one thread that delivers them in order.

    A daemon thread, so a chat that does not answer cannot keep the bot
    from stopping; ``stop`` gives the queue a few seconds first and reports
    what is left.
    """

    def __init__(self, deliver: Callable[[str, float], None], clock: Clock, report: Callable[[str], None],
                 capacity: int = CAPACITY):
        self._deliver = deliver
        self._clock = clock
        self._report = report
        self._queue = queue.Queue(maxsize=capacity)
        # Counted under one lock: notify runs on every webhook thread.
        self._dropped = 0
        self._sending = 0
        self._state = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self._run, name="telegram-notifier", daemon=True).start()

    def notify(self, text: str) -> None:
        try:
            self._queue.put_nowait((text, self._clock.now()))
        except queue.Full:
            with self._state:
                self._dropped += 1
            self._report(f'Telegram: the "{_name(text)}" message was not sent: '
                         f"{self._queue.maxsize} messages were already waiting")

    def stop(self, seconds: float) -> None:
        """Waits up to ``seconds`` for the queue to empty, then reports the
        messages still in it, which the stop loses, and a count of dropped
        messages the chat has not heard of yet."""
        done = threading.Event()
        # A marker put behind the messages: once the thread reaches it, every
        # message before it has been handled.
        try:
            self._queue.put_nowait((done, self._clock.now()))
            marker = 1
        except queue.Full:
            marker = 0
        drained = done.wait(seconds)
        with self._state:
            left = 0 if drained else max(self._queue.qsize() - marker, 0) + self._sending
            dropped, self._dropped = self._dropped, 0
        if left:
            self._report(f"Telegram: the bot stopped with {left} of its messages not sent; the log has them")
        if dropped:
            self._report(f"Telegram: the queue was full and dropped {dropped} of the bot's messages; "
                         "the log has them")

    def _run(self) -> None:
        while True:
            text, logged_at = self._queue.get()
            if isinstance(text, threading.Event):
                text.set()
                continue
            # Any exception, so one message's failure cannot end the thread
            # and silence every message after it. By type alone: its text
            # could hold the request, and the token in it.
            with self._state:
                self._sending = 1
            try:
                self._deliver(text, logged_at)
            except Exception as error:
                self._report(f'Telegram: the "{_name(text)}" message was not sent: '
                             f"an error in the bot ({type(error).__name__})")
            with self._state:
                self._sending = 0
            self._send_dropped()

    def _send_dropped(self) -> None:
        # Once the queue is empty, the phone hears that messages were lost,
        # not only the log: a flood of rejections may have pushed out the one
        # that needed action. Not before: in a full queue this message would
        # be dropped too.
        if not self._queue.empty():
            return
        with self._state:
            dropped, self._dropped = self._dropped, 0
        if dropped:
            self.notify(f"Telegram: the queue was full and dropped {dropped} of the bot's messages; the log has them")
