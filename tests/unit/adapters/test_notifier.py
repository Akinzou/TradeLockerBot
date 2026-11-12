"""The notifier: tries a message again while the chat may get over the
failure, says when a message comes late, and sends from its own thread, so
no signal waits on the chat (ADR 0027)."""

import math
import threading

import pytest

from tests.fake_clock import FakeClock
from tradelocker_bot.adapters.notifier import ATTEMPTS, BackgroundNotifier, Delivery, SendFailure
from tradelocker_bot.domain.result import Err, Ok

WAIT_SECONDS = 5
TEXT = "Signal rejected: line 2 (direction) is 'long', expected buy or sell"


class Chat:
    """Answers each send with the next of ``answers``, and records the texts."""

    def __init__(self, *answers):
        self.sent = []
        self._answers = list(answers)

    def send(self, text):
        self.sent.append(text)
        return self._answers.pop(0)


def _deliver(chat):
    sleeps, reports = [], []
    clock = FakeClock(sleeps.append)
    return Delivery(chat, clock, reports.append), clock, sleeps, reports


def test_a_sent_message_is_sent_once_and_not_reported():
    chat = Chat(Ok(None))
    deliver, _, sleeps, reports = _deliver(chat)

    deliver(TEXT, 0.0)

    assert (chat.sent, sleeps, reports) == ([TEXT], [], [])


def test_a_failure_the_chat_may_get_over_is_tried_again_after_a_growing_wait():
    chat = Chat(Err(SendFailure("HTTP 502", retry=True)), Err(SendFailure("no answer (TimeoutError)", retry=True)),
                Ok(None))
    deliver, _, sleeps, reports = _deliver(chat)

    deliver(TEXT, 0.0)

    assert chat.sent == [TEXT] * 3
    assert sleeps == [("sleep", 2.0), ("sleep", 10.0)]
    assert reports == []


def test_the_chats_own_wait_is_kept_up_to_ten_minutes():
    # A try before Telegram's wait ends is refused too, so a shorter cap
    # would spend the tries and lose the message.
    chat = Chat(Err(SendFailure("HTTP 429", retry=True, retry_after=120.0)),
                Err(SendFailure("HTTP 429", retry=True, retry_after=86400.0)), Ok(None))
    deliver, _, sleeps, _ = _deliver(chat)

    deliver(TEXT, 0.0)

    assert sleeps == [("sleep", 120.0), ("sleep", 600.0)]


@pytest.mark.parametrize("asked", [-1.0, math.nan, math.inf])
def test_a_wait_no_server_means_gets_the_usual_one(asked):
    chat = Chat(Err(SendFailure("HTTP 429", retry=True, retry_after=asked)), Ok(None))
    deliver, _, sleeps, reports = _deliver(chat)

    deliver(TEXT, 0.0)

    assert (sleeps, reports) == ([("sleep", 2.0)], [])


def test_a_failure_that_lasts_is_reported_once_after_the_last_try():
    chat = Chat(*[Err(SendFailure("HTTP 502", retry=True))] * ATTEMPTS)
    deliver, _, _, reports = _deliver(chat)

    deliver(TEXT, 0.0)

    assert len(chat.sent) == ATTEMPTS == 3
    assert reports == [f'Telegram: the "Signal rejected" message was not sent after {ATTEMPTS} tries: HTTP 502']


def test_a_failure_the_same_request_would_get_again_is_reported_at_once():
    chat = Chat(Err(SendFailure("HTTP 403, 'Forbidden: bot was blocked by the user'", retry=False)))
    deliver, _, sleeps, reports = _deliver(chat)

    deliver("Logged in: acc_id 76, acc_num 1", 0.0)

    assert (len(chat.sent), sleeps) == (1, [])
    assert reports == ["Telegram: the \"Logged in\" message was not sent: "
                       "HTTP 403, 'Forbidden: bot was blocked by the user'"]


def test_a_message_sent_a_minute_or_more_after_it_was_logged_says_how_late_it_is():
    chat = Chat(Ok(None), Err(SendFailure("HTTP 502", retry=True)), Ok(None))
    deliver, clock, _, _ = _deliver(chat)
    clock.advance(59.9)
    deliver(TEXT, 0.0)

    # The last try is the one that goes, after 2 more seconds.
    deliver(TEXT, 0.0)

    # First, so the cut to Telegram's longest message never takes it.
    assert chat.sent == [TEXT, TEXT, f"(sent 61 seconds after the bot logged it)\n{TEXT}"]


@pytest.mark.parametrize("text", ["Still closing: XAUUSD", "Still closing"])
def test_the_report_names_the_message_by_its_first_words(text):
    chat = Chat(Err(SendFailure("HTTP 400", retry=False)))
    deliver, _, _, reports = _deliver(chat)

    deliver(text, 0.0)

    assert reports == ['Telegram: the "Still closing" message was not sent: HTTP 400']


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

    notifier.stop(WAIT_SECONDS)

    assert [text for text, _ in deliver.delivered] == ["first", "last"]
    assert reports == []


def test_the_stop_reports_the_messages_it_loses_rather_than_waiting_for_them():
    deliver = GatedDelivery()
    notifier, _, reports = _started(deliver)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.notify("second")
    notifier.notify("last")

    notifier.stop(0.1)

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

    notifier.stop(0.1)

    assert reports == ["Telegram: the bot stopped with 2 of its messages not sent; the log has them",
                       "Telegram: the queue was full and dropped 1 of the bot's messages; the log has them"]
    deliver.gate.set()
