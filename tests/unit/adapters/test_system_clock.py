"""``SystemClock`` reads the monotonic clock and sleeps the thread."""

import time

from tradelocker_bot.adapters.system_clock import SystemClock


def test_now_is_the_monotonic_clock_not_the_wall_clock(monkeypatch):
    # The wall clock can step back or forward (NTP, a manual change), which
    # would ask the broker again at once or not for an hour (ADR 0022).
    monkeypatch.setattr(time, "monotonic", lambda: 1234.5)
    monkeypatch.setattr(time, "time", lambda: 9.0)

    assert SystemClock().now() == 1234.5


def test_sleep_sleeps_the_calling_thread_for_the_given_seconds(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)

    SystemClock().sleep(1.0)

    assert slept == [1.0]
