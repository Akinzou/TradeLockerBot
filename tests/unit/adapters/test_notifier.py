"""The notifier: tries a message again while Telegram may get over the
failure, and sends from its own thread, so no signal waits on Telegram
(ADR 0027)."""

import threading

import pytest

from tests.fake_clock import FakeClock
from tradelocker_bot.adapters.notifier import ATTEMPTS, BackgroundNotifier, Delivery
from tradelocker_bot.adapters.telegram import SendFailure
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
    deliver = Delivery(chat, FakeClock(sleeps.append), reports.append)
    return deliver, sleeps, reports


def test_a_sent_message_is_sent_once_and_not_reported():
    chat = Chat(Ok(None))
    deliver, sleeps, reports = _deliver(chat)

    deliver(TEXT)

    assert (chat.sent, sleeps, reports) == ([TEXT], [], [])


def test_a_failure_telegram_may_get_over_is_tried_again_after_a_growing_wait():
    chat = Chat(Err(SendFailure("HTTP 502", retry=True)), Err(SendFailure("no answer (TimeoutError)", retry=True)),
                Ok(None))
    deliver, sleeps, reports = _deliver(chat)

    deliver(TEXT)

    assert chat.sent == [TEXT] * 3
    assert sleeps == [("sleep", 2.0), ("sleep", 10.0)]
    assert reports == []


def test_telegrams_own_wait_is_kept_up_to_a_minute():
    chat = Chat(Err(SendFailure("HTTP 429", retry=True, retry_after=7.0)),
                Err(SendFailure("HTTP 429", retry=True, retry_after=3600.0)), Ok(None))
    deliver, sleeps, _ = _deliver(chat)

    deliver(TEXT)

    assert sleeps == [("sleep", 7.0), ("sleep", 60.0)]


def test_a_failure_that_lasts_is_reported_once_after_the_last_try():
    chat = Chat(*[Err(SendFailure("HTTP 502", retry=True))] * ATTEMPTS)
    deliver, _, reports = _deliver(chat)

    deliver(TEXT)

    assert len(chat.sent) == ATTEMPTS == 3
    assert reports == [f'Telegram: the "Signal rejected" message was not sent after {ATTEMPTS} tries: HTTP 502']


def test_a_failure_the_same_request_would_get_again_is_reported_at_once():
    chat = Chat(Err(SendFailure("HTTP 403, 'Forbidden: bot was blocked by the user'", retry=False)))
    deliver, sleeps, reports = _deliver(chat)

    deliver("Logged in: acc_id 76, acc_num 1")

    assert (len(chat.sent), sleeps) == (1, [])
    assert reports == ["Telegram: the \"Logged in\" message was not sent: "
                       "HTTP 403, 'Forbidden: bot was blocked by the user'"]


class GatedDelivery:
    """Holds each message until the test opens the gate, so the test knows
    where the worker is."""

    def __init__(self):
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.delivered = []
        self.done = threading.Event()

    def __call__(self, text):
        self.entered.set()
        assert self.gate.wait(WAIT_SECONDS)
        if text == "raises":
            raise RuntimeError(f"a bug, with {text}")
        self.delivered.append(text)
        if text == "last":
            self.done.set()


def _started(deliver, capacity=10):
    reports = []
    notifier = BackgroundNotifier(deliver, reports.append, capacity=capacity)
    notifier.start()
    return notifier, reports


def test_a_message_waits_for_telegram_on_the_notifiers_thread_not_the_callers():
    deliver = GatedDelivery()
    notifier, _ = _started(deliver)

    notifier.notify("first")
    notifier.notify("last")

    # Both returned while the first is still held.
    assert deliver.entered.wait(WAIT_SECONDS)
    assert deliver.delivered == []
    deliver.gate.set()
    assert deliver.done.wait(WAIT_SECONDS)
    assert deliver.delivered == ["first", "last"]


def test_a_message_beyond_the_queue_is_reported_rather_than_waited_for():
    deliver = GatedDelivery()
    notifier, reports = _started(deliver, capacity=1)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.notify("last")

    notifier.notify("Order rejected: the broker refused to buy XAUUSD")

    assert reports == ['Telegram: the "Order rejected" message was not sent: 1 message was already waiting']
    deliver.gate.set()
    assert deliver.done.wait(WAIT_SECONDS)
    assert deliver.delivered == ["first", "last"]


def test_a_delivery_that_raises_is_reported_by_type_and_the_next_message_still_goes():
    deliver = GatedDelivery()
    deliver.gate.set()
    notifier, reports = _started(deliver)

    notifier.notify("raises")
    notifier.notify("last")

    assert deliver.done.wait(WAIT_SECONDS)
    assert reports == ['Telegram: the "raises" message was not sent: an error in the bot (RuntimeError)']


@pytest.mark.parametrize("text", ["Still closing: XAUUSD", "Still closing"])
def test_the_report_names_the_message_by_its_first_words(text):
    chat = Chat(Err(SendFailure("HTTP 400", retry=False)))
    deliver, _, reports = _deliver(chat)

    deliver(text)

    assert reports == ['Telegram: the "Still closing" message was not sent: HTTP 400']
