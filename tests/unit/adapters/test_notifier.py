"""``Delivery``: tries a message again while the chat may get over the
failure, and says when a message comes late (ADR 0027). The queue and its
thread are pinned in ``test_background_notifier.py``."""

import math

import pytest

from tests.fake_clock import FakeClock
from tradelocker_bot.adapters.notifier import ATTEMPTS, Delivery, SendFailure
from tradelocker_bot.domain.result import Err, Ok

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
