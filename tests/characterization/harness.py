"""Shared seam for characterization tests.

This is the only place that knows where the handler under test lives. When a
structure step moves it, only this module changes, and the pull request calls
that out (ADR 0001).
"""

import threading
from types import MappingProxyType

import main_without_ssl as bot
from tests.characterization.fake_tradelocker import FakeTradeLocker

XAUUSD_ID = 101
EURUSD_ID = 202

# One shared literal, so a declared change to an order field is made in one
# place; read-only, so no test can alter the expectation for the tests after it.
# It lists every parameter, defaults included, because the fake records the
# full request the broker receives.
DEFAULT_ORDER = MappingProxyType({
    "quantity": 0.1,
    "side": "buy",
    "price": None,
    "type_": "market",
    "validity": None,
    "position_netting": False,
    "take_profit": 500,
    "take_profit_type": "offset",
    "stop_loss": 1000,
    "stop_loss_type": "offset",
    "stop_price": None,
    "strategy_id": None,
    "_ignore_len_check": False,
})

LOCK_ACQUIRED = "[lock acquired]"
LOCK_RELEASED = "[lock released]"


def payload(action="open", direction="buy", lot="0.01/100", tp="500", sl="1000", invert="NonInvert"):
    return ["XAUUSD", direction, lot, tp, sl, action, invert]


def broker(balance=1000.0, open_positions=(), order_results=(9001,), close_requests_to_fill=1):
    return FakeTradeLocker(
        balance=balance,
        instrument_ids={"XAUUSD": XAUUSD_ID, "EURUSD": EURUSD_ID},
        open_positions=open_positions,
        order_results=order_results,
        close_requests_to_fill=close_requests_to_fill,
    )


class RecordingLock:
    """A real lock that logs, per acquire and release, how many broker calls
    had happened by then.

    Chosen over asking the lock ``locked()`` on every broker call: that flag is
    true both for one critical section and for one per call, and only the first
    keeps two webhook threads from interleaving between close and order.

    It also prints a marker line, so pinned console output shows which operator
    lines are written inside the critical section.
    """

    def __init__(self, fake):
        self._lock = threading.Lock()
        self._fake = fake
        self.events = []

    def acquire(self, blocking=True, timeout=-1):
        acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            self.events.append(("acquire", len(self._fake.calls)))
            print(LOCK_ACQUIRED)
        return acquired

    def release(self):
        # Record while still holding the lock, so no other thread's acquire can
        # appear before this release; refuse first when not held, so a double
        # release fails without leaving a false record.
        if not self._lock.locked():
            raise RuntimeError("release unlocked lock")
        self.events.append(("release", len(self._fake.calls)))
        print(LOCK_RELEASED)
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    __enter__ = acquire

    def __exit__(self, *exc_info):
        self.release()


def handle(fake, lines, lock=None):
    bot.handle_position_normal(fake, lines, lock if lock is not None else threading.Lock())
