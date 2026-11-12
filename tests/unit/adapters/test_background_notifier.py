"""``BackgroundNotifier``: sends from its own thread, so no signal waits on
the chat, and drops and counts what a full queue cannot hold (ADR 0027,
ADR 0029). The stop is pinned in ``test_notifier_stop.py``."""

from tests.unit.adapters.notifier_doubles import WAIT_SECONDS, GatedDelivery, StepDelivery, started


def _count(dropped):
    return f"Telegram: the queue was full and dropped {dropped} of the bot's messages; the log has them"


def test_a_message_waits_for_the_chat_on_the_notifiers_thread_not_the_callers():
    deliver = GatedDelivery()
    notifier, clock, _, _ = started(deliver)

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


def test_a_message_beyond_the_queue_is_dropped_reported_and_counted_to_the_chat():
    deliver = GatedDelivery(last="Telegram: the queue was full")
    notifier, _, reports, _ = started(deliver, capacity=2)
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
    assert [text for text, _ in deliver.delivered] == ["first", "second", "last", _count(2)]


def test_a_delivery_that_raises_is_reported_by_type_and_the_next_message_still_goes():
    deliver = GatedDelivery()
    deliver.gate.set()
    notifier, _, reports, _ = started(deliver)

    notifier.notify("raises")
    notifier.notify("last")

    assert deliver.done.wait(WAIT_SECONDS)
    assert reports == ['Telegram: the "raises" message was not sent: an error in the bot (RuntimeError)']


def test_the_count_waits_where_the_first_drop_was_takes_no_line_s_slot_and_grows_while_it_waits():
    # Under steady traffic the queue may never be empty, so a count that
    # waited for that could wait for hours; one in its place, in order,
    # goes as the lines around it do (ADR 0029).
    deliver = StepDelivery()
    notifier, clock, _, _ = started(deliver, capacity=2)
    notifier.notify("first")
    deliver.reach("first")
    notifier.notify("second")
    notifier.notify("third")
    clock.advance(5.0)
    notifier.notify("dropped at 5 seconds")
    deliver.allowed.release()
    deliver.reach("second")

    # Room for two lines, the count waiting beside them.
    notifier.notify("fourth")
    clock.advance(5.0)
    notifier.notify("dropped at 10 seconds")
    deliver.allowed.release(5)

    deliver.reach("third")
    # Logged at the first drop it counts, so a lateness note covers it.
    assert deliver.reach(_count(2)) == 5.0
    deliver.reach("fourth")


def test_a_drop_while_the_count_is_being_sent_starts_a_new_count():
    # The count in flight cannot take it any more; a drop counted in
    # neither would be lost, and in both told twice.
    deliver = StepDelivery()
    notifier, _, _, _ = started(deliver, capacity=1)
    notifier.notify("first")
    deliver.reach("first")
    notifier.notify("second")
    notifier.notify("dropped")
    deliver.allowed.release()
    deliver.reach("second")
    notifier.notify("third")
    deliver.allowed.release()
    deliver.reach(_count(1))

    notifier.notify("dropped while the count is sent")

    deliver.allowed.release(3)
    deliver.reach("third")
    deliver.reach(_count(1))
