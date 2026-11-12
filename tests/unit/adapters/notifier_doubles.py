"""Deliveries that let a test know where the notifier's thread is, shared by
the queue's tests and the stop's."""

import queue
import threading

from tests.fake_clock import FakeClock
from tradelocker_bot.adapters.notifier import BackgroundNotifier

WAIT_SECONDS = 5


class GatedDelivery:
    """Holds each message until the test opens the gate, so the test knows
    where the worker is."""

    def __init__(self, last="last"):
        self.last = last
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.delivered = []
        self.done = threading.Event()

    def __call__(self, text, logged_at, stopped):
        self.entered.set()
        assert self.gate.wait(WAIT_SECONDS)
        if text == "raises":
            raise RuntimeError(f"a bug, with {text}")
        self.delivered.append((text, logged_at))
        if text.startswith(self.last):
            self.done.set()


class StepDelivery:
    """Delivers one message each time the test allows one, and tells the
    test which message it has reached."""

    def __init__(self):
        self.reached = queue.Queue()
        self.allowed = threading.Semaphore(0)
        self.delivered = []

    def __call__(self, text, logged_at, stopped):
        self.reached.put((text, logged_at))
        assert self.allowed.acquire(timeout=WAIT_SECONDS)
        self.delivered.append(text)

    def reach(self, text):
        reached, logged_at = self.reached.get(timeout=WAIT_SECONDS)
        assert reached == text
        return logged_at


def started(deliver, capacity=10, floor=0.0):
    """A started notifier on a clock that moves only when the test moves
    it, its reports, and its thread, so a test can tell that it ended."""
    reports = []
    clock = FakeClock(lambda sleep: None)
    notifier = BackgroundNotifier(deliver, clock, reports.append, floor=floor, capacity=capacity)
    before = set(threading.enumerate())
    notifier.start()
    [thread] = set(threading.enumerate()) - before
    return notifier, clock, reports, thread
