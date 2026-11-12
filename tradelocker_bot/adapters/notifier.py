"""Hands the operator's alerts to Telegram without making a signal wait for
it (ADR 0027).

The console calls ``notify`` inside the lock every signal shares, so a slow
or unreachable Telegram must cost the trading path nothing: ``notify`` only
queues, and one thread of the notifier's own sends, in order, trying a
message again while Telegram may get over the failure. Every message it
cannot send is reported to the log, by the words it starts with: the line
itself is already there, printed by the console.
"""

import queue
import threading
from collections.abc import Callable

from tradelocker_bot.adapters import ascii_alerts
from tradelocker_bot.application.ports import Clock
from tradelocker_bot.domain.result import Err

ATTEMPTS = 3

# Between the tries, when Telegram names no wait of its own: a dropped
# connection is usually back within seconds, a restarting server within
# tens of them.
WAITS_SECONDS = (2.0, 10.0)

# Telegram's own wait is kept up to this, so one message cannot hold the
# rest for longer than a minute per try.
MAX_WAIT_SECONDS = 60.0

# Far above what a burst of alerts queues while Telegram answers; a flood
# beyond it is dropped and reported rather than held in memory.
CAPACITY = 100

# The words a report names a message by; every line the bot sends starts
# with a few words and a colon.
NAMED_CHARACTERS = 40


def print_report(line: str) -> None:
    """The log line for a message not sent: red, as the lines it was for,
    and never itself sent, so a Telegram outage cannot feed on itself."""
    print(f"{ascii_alerts.RED}{line}\n{ascii_alerts.RESET}")


def _name(text: str) -> str:
    return text.partition(":")[0][:NAMED_CHARACTERS]


class Delivery:
    """Sends one message, trying it again on a failure Telegram may get
    over, and reports it when it is not sent."""

    def __init__(self, chat, clock: Clock, report: Callable[[str], None]):
        self._chat = chat
        self._clock = clock
        self._report = report

    def __call__(self, text: str) -> None:
        for attempt in range(1, ATTEMPTS + 1):
            sent = self._chat.send(text)
            if not isinstance(sent, Err):
                return
            failure = sent.error
            if not failure.retry:
                self._report(f'Telegram: the "{_name(text)}" message was not sent: {failure.reason}')
                return
            if attempt < ATTEMPTS:
                wait = WAITS_SECONDS[attempt - 1] if failure.retry_after is None else failure.retry_after
                self._clock.sleep(min(wait, MAX_WAIT_SECONDS))
        self._report(f'Telegram: the "{_name(text)}" message was not sent after {ATTEMPTS} tries: {failure.reason}')


class BackgroundNotifier:
    """Queues each message for one thread that delivers them in order.

    A daemon thread: messages still queued when the bot stops are lost,
    rather than holding the stop for a minute of tries. Every one of them
    is in the log already.
    """

    def __init__(self, deliver: Callable[[str], None], report: Callable[[str], None], capacity: int = CAPACITY):
        self._deliver = deliver
        self._report = report
        self._capacity = capacity
        self._queue = queue.Queue(maxsize=capacity)

    def start(self) -> None:
        threading.Thread(target=self._run, name="telegram-notifier", daemon=True).start()

    def notify(self, text: str) -> None:
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            waiting = "1 message was" if self._capacity == 1 else f"{self._capacity} messages were"
            self._report(f'Telegram: the "{_name(text)}" message was not sent: {waiting} already waiting')

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            # Any exception, so one message's failure cannot end the thread
            # and silence every message after it. By type alone: its text
            # could hold the request, and the token in it.
            try:
                self._deliver(text)
            except Exception as error:
                self._report(f'Telegram: the "{_name(text)}" message was not sent: '
                             f"an error in the bot ({type(error).__name__})")
