"""Shared seam for characterization tests.

This is the only place that knows where the handler under test lives. When a
structure step moves it, only this module changes, and the pull request calls
that out (ADR 0001).
"""

import threading

import main_without_ssl as bot
from tests.characterization.fake_tradelocker import FakeTradeLocker

XAUUSD_ID = 101
EURUSD_ID = 202


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


def handle(fake, lines):
    bot.handle_position_normal(fake, lines, threading.Lock())
