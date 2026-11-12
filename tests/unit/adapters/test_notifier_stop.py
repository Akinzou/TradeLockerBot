"""``BackgroundNotifier.stop``: gives the queue its seconds, reports what
it loses, and sends nothing after that report (ADR 0027, ADR 0029)."""

import threading

from tests.unit.adapters.notifier_doubles import WAIT_SECONDS, GatedDelivery, StepDelivery, started

NOT_SENT_1 = "Telegram: the bot stopped with 1 of its messages not sent; the log has them"


def _open_later(deliver, seconds=0.3):
    # Real time: the stop waits on a condition, which the fake clock does
    # not drive.
    timer = threading.Timer(seconds, deliver.gate.set)
    timer.start()
    return timer


def test_the_stop_waits_for_the_queue_and_reports_nothing_when_it_empties():
    deliver = GatedDelivery()
    deliver.gate.set()
    notifier, _, reports, _ = started(deliver)
    notifier.notify("first")
    notifier.notify("last")

    notifier.end(WAIT_SECONDS)
    notifier.stop()

    assert [text for text, _ in deliver.delivered] == ["first", "last"]
    assert reports == []


def test_the_stop_reports_the_messages_it_loses_rather_than_waiting_for_them():
    deliver = GatedDelivery()
    notifier, _, reports, _ = started(deliver)
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
    notifier, _, reports, _ = started(deliver, capacity=1)
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
    notifier, clock, reports, _ = started(deliver)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.end(5.0)
    clock.advance(6.0)

    notifier.stop()

    assert reports == [NOT_SENT_1]
    deliver.gate.set()


def test_a_line_queued_after_the_end_seconds_ran_out_still_gets_the_floor():
    # A signal still running when `main` ends, after a second Ctrl+C: its
    # line has a terminal with no deadline of its own, or what is left of
    # docker stop's (ADR 0029).
    deliver = GatedDelivery()
    notifier, clock, reports, _ = started(deliver, floor=WAIT_SECONDS)
    notifier.end(5.0)
    clock.advance(6.0)
    notifier.notify("Broker failed: a call for XAUUSD got no answer")
    timer = _open_later(deliver)

    notifier.stop()

    timer.join()
    assert [text for text, _ in deliver.delivered] == ["Broker failed: a call for XAUUSD got no answer"]
    assert reports == []


def test_without_an_end_the_stop_still_waits_the_floor():
    # `main` can miss its `finally`, when a second Ctrl+C lands in it.
    deliver = GatedDelivery()
    notifier, _, reports, _ = started(deliver, floor=WAIT_SECONDS)
    notifier.notify("first")
    timer = _open_later(deliver)

    notifier.stop()

    timer.join()
    assert [text for text, _ in deliver.delivered] == ["first"]
    assert reports == []


def test_the_floor_does_not_cut_the_seconds_the_end_set_aside():
    deliver = GatedDelivery()
    notifier, _, reports, _ = started(deliver, floor=0.1)
    notifier.notify("first")
    notifier.end(WAIT_SECONDS)
    timer = _open_later(deliver)

    notifier.stop()

    timer.join()
    assert reports == []


def test_after_the_stop_the_thread_ends_and_sends_nothing_it_reported():
    # The report says the log has them; a send after it would make the
    # report wrong (ADR 0029).
    deliver = GatedDelivery()
    notifier, _, reports, thread = started(deliver)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)
    notifier.notify("second")
    notifier.end(0.1)
    notifier.stop()

    deliver.gate.set()
    thread.join(WAIT_SECONDS)

    assert not thread.is_alive()
    # The try already under way when the stop came, and nothing after it.
    assert [text for text, _ in deliver.delivered] == ["first"]
    assert reports == ["Telegram: the bot stopped with 2 of its messages not sent; the log has them"]


def test_the_delivery_learns_of_the_stop_between_its_tries():
    seen = []
    entered, stopping = threading.Event(), threading.Event()

    def deliver(text, logged_at, stopped):
        seen.append(stopped())
        entered.set()
        stopping.wait(WAIT_SECONDS)
        seen.append(stopped())

    notifier, _, _, thread = started(deliver)
    notifier.notify("first")
    assert entered.wait(WAIT_SECONDS)
    notifier.end(0.0)
    notifier.stop()
    stopping.set()
    thread.join(WAIT_SECONDS)

    assert seen == [False, True]


def test_a_line_after_the_stop_is_reported_rather_than_queued_for_nobody():
    deliver = GatedDelivery()
    deliver.gate.set()
    notifier, _, reports, _ = started(deliver)
    notifier.stop()

    notifier.notify("Bot failed: an error in the bot (RuntimeError) while handling XAUUSD")

    assert reports == ['Telegram: the "Bot failed" message was not sent: the bot had stopped']


def test_a_dropped_count_at_the_stop_is_reported_as_a_count_not_as_a_line():
    deliver = StepDelivery()
    notifier, _, reports, _ = started(deliver, capacity=1)
    notifier.notify("first")
    deliver.reach("first")
    notifier.notify("second")
    notifier.notify("dropped")
    deliver.allowed.release()
    deliver.reach("second")
    notifier.notify("third")
    deliver.allowed.release()
    deliver.reach("Telegram: the queue was full and dropped 1 of the bot's messages; the log has them")
    notifier.notify("dropped while the count is sent")
    reports.clear()

    notifier.end(0.1)
    notifier.stop()

    # The count being sent and the one waiting, as one count; the line
    # between them as a line.
    assert reports == [NOT_SENT_1,
                       "Telegram: the queue was full and dropped 2 of the bot's messages; the log has them"]
    deliver.allowed.release()


def _stopped_while_sending(outcome):
    """A delivery that is under way when the stop reports, and then ends
    with ``outcome``: a report of its own, or an exception."""
    entered, stopping = threading.Event(), threading.Event()

    def deliver(text, logged_at, stopped):
        entered.set()
        stopping.wait(WAIT_SECONDS)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return deliver, entered, stopping


def test_a_message_the_stop_reported_is_not_reported_again_when_its_try_fails_after():
    # One message, one red line: the stop counted it, so the delivery's own
    # report, or its exception's, would count it twice (ADR 0029).
    for outcome in ['Telegram: the "first" message was not sent after 3 tries: HTTP 502', RuntimeError("a bug")]:
        deliver, entered, stopping = _stopped_while_sending(outcome)
        notifier, _, reports, thread = started(deliver)
        notifier.notify("first")
        assert entered.wait(WAIT_SECONDS)
        notifier.end(0.0)
        notifier.stop()

        stopping.set()
        thread.join(WAIT_SECONDS)

        assert not thread.is_alive()
        assert reports == [NOT_SENT_1]


def test_a_delivery_s_report_is_printed_when_no_stop_counted_the_message():
    notifier, _, reports, _ = started(lambda text, logged_at, stopped: f'Telegram: the "{text}" message was not sent')

    notifier.notify("first")
    notifier.end(WAIT_SECONDS)
    notifier.stop()

    assert reports == ['Telegram: the "first" message was not sent']


def test_an_interrupt_during_the_stop_s_wait_cuts_the_wait_not_the_report(monkeypatch):
    # A third Ctrl+C on a terminal, while the floor runs: the operator wants
    # out sooner, and still needs to know what was lost.
    deliver = GatedDelivery()
    notifier, _, reports, thread = started(deliver, floor=WAIT_SECONDS)
    notifier.notify("first")
    assert deliver.entered.wait(WAIT_SECONDS)

    # Only the stop's own wait, on this thread, as Python delivers Ctrl+C.
    wait_for = notifier._state.wait_for

    def interrupted(predicate, timeout=None):
        if threading.current_thread() is threading.main_thread():
            raise KeyboardInterrupt
        return wait_for(predicate, timeout)

    monkeypatch.setattr(notifier._state, "wait_for", interrupted)
    notifier.stop()

    assert reports == [NOT_SENT_1]
    deliver.gate.set()
    thread.join(WAIT_SECONDS)
    assert not thread.is_alive()
