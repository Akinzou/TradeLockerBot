"""``BackgroundNotifier``: sends from its own thread, so no signal waits on
the chat, drops and counts what a full queue cannot hold, and gives the
queue its seconds at the stop (ADR 0027)."""

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

    def __call__(self, text, logged_at):
        self.entered.set()
        assert self.gate.wait(WAIT_SECONDS)
        if text == "raises":
            raise RuntimeError(f"a bug, with {text}")
        self.delivered.append((text, logged_at))
        if text.startswith(self.last):
            self.done.set()


def _started(deliver, capacity=10):
    reports = []
    clock = FakeClock(lambda sleep: None)
    notifier = BackgroundNotifier(deliver, clock, reports.append, capacity=capacity)
    notifier.start()
    return notifier, clock, reports


def test_a_message_waits_for_the_chat_on_the_notifiers_thread_not_the_callers():
    deliver = GatedDelivery()
    notifier, clock, _ = _started(deliver)

    notifier.notify("first")
    clock.advance(30.0)
    notifier.notify("last")

    # Both returned while the first is still held.
    assert deliver.entered.wait(WAIT_SECONDS)
    assert deliver.delivered == []
    deliver.gate.set()
    assert deliver.done.wait(WAIT_SECONDS)
    # Each with the time it was logged, not the time it is sent.
    assert deliver.delivered == [("first", 0.0), ("last", 30.0)]


def test_a_message_beyond_the_queue_is_dropped_and_the_chat_hears_how_many_once_there_is_room():
    deliver = GatedDelivery(last="Telegram: the queue was full")
    notifier, _, reports = _started(deliver, capacity=2)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.notify("second")
    notifier.notify("last")

    notifier.notify("Order rejected: the broker refused to buy XAUUSD")
    notifier.notify("Broker failed: a call for XAUUSD got no answer")

    assert reports == ['Telegram: the "Order rejected" message was not sent: the queue of 2 was full',
                       'Telegram: the "Broker failed" message was not sent: the queue of 2 was full']
    deliver.gate.set()
    assert deliver.done.wait(WAIT_SECONDS)
    assert [text for text, _ in deliver.delivered] == [
        "first", "second", "last", "Telegram: the queue was full and dropped 2 of the bot's messages; the log has them"]


def test_a_delivery_that_raises_is_reported_by_type_and_the_next_message_still_goes():
    deliver = GatedDelivery()
    deliver.gate.set()
    notifier, _, reports = _started(deliver)

    notifier.notify("raises")
    notifier.notify("last")

    assert deliver.done.wait(WAIT_SECONDS)
    assert reports == ['Telegram: the "raises" message was not sent: an error in the bot (RuntimeError)']


def test_the_stop_waits_for_the_queue_and_reports_nothing_when_it_empties():
    deliver = GatedDelivery()
    deliver.gate.set()
    notifier, _, reports = _started(deliver)
    notifier.notify("first")
    notifier.notify("last")

    notifier.end(WAIT_SECONDS)
    notifier.stop()

    assert [text for text, _ in deliver.delivered] == ["first", "last"]
    assert reports == []


def test_the_stop_reports_the_messages_it_loses_rather_than_waiting_for_them():
    deliver = GatedDelivery()
    notifier, _, reports = _started(deliver)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.notify("second")
    notifier.notify("last")

    notifier.end(0.1)
    notifier.stop()

    # The one being sent and the two behind it.
    assert reports == ["Telegram: the bot stopped with 3 of its messages not sent; the log has them"]
    deliver.gate.set()


def test_the_stop_reports_a_dropped_count_the_chat_has_not_heard_of():
    deliver = GatedDelivery()
    notifier, _, reports = _started(deliver, capacity=1)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.notify("second")
    notifier.notify("Order rejected: the broker refused to buy XAUUSD")
    reports.clear()

    notifier.end(0.1)
    notifier.stop()

    assert reports == ["Telegram: the bot stopped with 2 of its messages not sent; the log has them",
                       "Telegram: the queue was full and dropped 1 of the bot's messages; the log has them"]
    deliver.gate.set()


def test_the_stop_counts_its_seconds_from_the_end_not_from_the_exit_function():
    # Python reaches the exit function only once the webhook's threads have
    # ended; docker stop's seconds run from its SIGTERM.
    deliver = GatedDelivery()
    notifier, clock, reports = _started(deliver)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.end(5.0)
    clock.advance(6.0)

    notifier.stop()

    assert reports == ["Telegram: the bot stopped with 1 of its messages not sent; the log has them"]
    deliver.gate.set()


class StepDelivery:
    """Delivers one message each time the test allows one, and tells the
    test which message it has reached."""

    def __init__(self):
        self.reached = queue.Queue()
        self.allowed = threading.Semaphore(0)
        self.delivered = []

    def __call__(self, text, logged_at):
        self.reached.put(text)
        assert self.allowed.acquire(timeout=WAIT_SECONDS)
        self.delivered.append(text)

    def reach(self, text):
        assert self.reached.get(timeout=WAIT_SECONDS) == text


def test_a_dropped_count_waits_until_no_line_does_so_a_flood_cannot_starve_the_lines():
    deliver = StepDelivery()
    notifier, _, _ = _started(deliver, capacity=2)
    notifier.notify("first")
    deliver.reach("first")
    notifier.notify("second")
    notifier.notify("third")
    notifier.notify("dropped")
    deliver.allowed.release()
    deliver.reach("second")
    deliver.allowed.release()
    deliver.reach("third")

    notifier.notify("fifth")

    deliver.allowed.release(3)
    deliver.reach("fifth")
    deliver.reach("Telegram: the queue was full and dropped 1 of the bot's messages; the log has them")
    assert deliver.delivered[:4] == ["first", "second", "third", "fifth"]


def test_a_dropped_count_still_waiting_at_the_stop_is_reported_as_a_count_not_as_a_line():
    deliver = StepDelivery()
    notifier, _, reports = _started(deliver, capacity=1)
    notifier.notify("first")
    deliver.reach("first")
    notifier.notify("second")
    notifier.notify("dropped")
    deliver.allowed.release()
    deliver.reach("second")
    deliver.allowed.release()
    deliver.reach("Telegram: the queue was full and dropped 1 of the bot's messages; the log has them")
    reports.clear()

    notifier.end(0.1)
    notifier.stop()

    assert reports == ["Telegram: the queue was full and dropped 1 of the bot's messages; the log has them"]
    deliver.allowed.release()
