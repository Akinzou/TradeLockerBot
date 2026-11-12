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

    def __call__(self, text: str, logged_at: float, stopped: Callable[[], bool]) -> None:
        for attempt in range(1, ATTEMPTS + 1):
            # The notifier's stop has reported this message as not sent, so
            # a try after it could only make that report wrong, and a report
            # of its own here would count the message twice.
            if stopped():
                return
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


def _count_text(dropped: int) -> str:
    return f"Telegram: the queue was full and dropped {dropped} of the bot's messages; the log has them"


@dataclass(frozen=True)
class _Line:
    """One of the bot's own lines, which the log already has."""

    text: str
    logged_at: float


@dataclass
class _Count:
    """The messages a full queue dropped, told to the chat as one message.

    Mutable on purpose: while it waits, each new drop adds to it rather than
    queueing a message of its own, so a flood costs the queue one entry.
    ``logged_at`` is the first drop's, so a lateness note covers them all.
    """

    logged_at: float
    dropped: int = 1


class BackgroundNotifier:
    """Queues each message for one thread that delivers them in order.

    A daemon thread, so a chat that does not answer cannot keep the bot
    from stopping; ``stop`` gives the queue its seconds, then reports what
    is left, and the thread sends nothing after that report.

    One condition guards everything: the waiting messages, the one being
    sent, the count and the stop. A queue with a lock of its own beside it
    was two states to keep in step, and the gaps between them lost messages
    from the count.
    """

    def __init__(self, deliver: Callable[[str, float, Callable[[], bool]], None], clock: Clock,
                 report: Callable[[str], None], floor: float, capacity: int = CAPACITY):
        self._deliver = deliver
        self._clock = clock
        self._report = report
        self._floor = floor
        self._capacity = capacity
        self._state = threading.Condition()
        self._waiting: collections.deque[_Line | _Count] = collections.deque()
        # The count still in the queue, which each drop joins. Once the
        # thread takes it, the next drop starts another, so each drop is
        # told once: by the count in flight or by the new one.
        self._count: _Count | None = None
        self._sending: _Line | _Count | None = None
        self._deadline: float | None = None
        self._stopped = False

    def start(self) -> None:
        threading.Thread(target=self._run, name="telegram-notifier", daemon=True).start()

    def notify(self, text: str) -> None:
        with self._state:
            refused = self._queue(text)
        if refused:
            self._report(f'Telegram: the "{_name(text)}" message was not sent: {refused}')

    def end(self, seconds: float) -> None:
        """Sets aside ``seconds`` from now, the bot's end, for ``stop``: not
        from when Python gets to its exit functions, after waiting for the
        webhook's threads."""
        with self._state:
            self._deadline = self._clock.now() + seconds

    def stop(self) -> None:
        """Waits for every message to be handled, until the time ``end`` set
        aside runs out but never less than the floor, then reports the
        bot's own lines still pending, which the stop loses, and the dropped
        messages the chat has not heard of.

        The floor is for a line queued after those seconds ran out, or with
        no ``end`` at all: both happen only after a second Ctrl+C, on a
        terminal, which kills nothing after a grace period. Under
        ``docker stop`` the server waits for every signal, so ``end`` comes
        after the last line and the floor is never reached.
        """
        with self._state:
            now = self._clock.now()
            left = self._floor if self._deadline is None else max(self._deadline - now, self._floor)
            self._state.wait_for(lambda: not self._waiting and self._sending is None, left)
            pending = [*self._waiting, *([self._sending] if self._sending else [])]
            # In the same step as the count, so a line queued from here on
            # is refused with a report rather than lost without one.
            self._stopped = True
            self._state.notify_all()
        lines = sum(isinstance(message, _Line) for message in pending)
        dropped = sum(message.dropped for message in pending if isinstance(message, _Count))
        if lines:
            self._report(f"Telegram: the bot stopped with {lines} of its messages not sent; the log has them")
        if dropped:
            self._report(_count_text(dropped))

    def _queue(self, text: str) -> str | None:
        # The caller holds the condition, so the checks and the change they
        # allow are one step for every thread. Returns why the line was
        # not queued, or None.
        if self._stopped:
            return "the bot had stopped"
        now = self._clock.now()
        # The count takes no line's slot: the queue holds `capacity` lines
        # and at most one count beside them.
        if len(self._waiting) - (self._count is not None) < self._capacity:
            self._waiting.append(_Line(text, now))
            self._state.notify_all()
            return None
        if self._count is None:
            # Queued now, behind the lines that filled the queue, rather than
            # once the queue empties: under steady traffic with a slow chat
            # that could take hours.
            self._count = _Count(now)
            self._waiting.append(self._count)
            self._state.notify_all()
        else:
            self._count.dropped += 1
        return f"the queue of {self._capacity} was full"

    def _has_stopped(self) -> bool:
        with self._state:
            return self._stopped

    def _run(self) -> None:
        while True:
            with self._state:
                self._state.wait_for(lambda: self._waiting or self._stopped)
                if self._stopped:
                    return
                message = self._sending = self._waiting.popleft()
                if message is self._count:
                    self._count = None
                # Read while the condition is held: a count no longer
                # waiting takes no more drops, so its text is final.
                text = message.text if isinstance(message, _Line) else _count_text(message.dropped)
            # Any exception, so one message's failure cannot end the thread
            # and silence every message after it. By type alone: its text
            # could hold the request, and the token in it.
            try:
                self._deliver(text, message.logged_at, self._has_stopped)
            except Exception as error:
                self._report(f'Telegram: the "{_name(text)}" message was not sent: '
                             f"an error in the bot ({type(error).__name__})")
            with self._state:
                self._sending = None
                self._state.notify_all()
