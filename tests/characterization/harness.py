"""Shared seam for characterization tests.

This is the only place that knows where the code under test lives: the
handler, the startup, the client login and the webhook path generator. When a
structure step moves any of them, only this module changes, and the pull
request calls that out (ADR 0001).
"""

import re
import sys
import threading
from types import MappingProxyType

from tradelocker.exceptions import TLAPIOrderException

import main_without_ssl as bot
from libs.URLgenerator import generate_random_url
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

# Recorded broker calls for the default payload, shared so a declared change
# to a call's shape is made in one place.
BALANCE = ("get_account_state",)
LOOKUP = ("get_all_instruments",)
POSITIONS = ("get_all_positions",)
CLOSE = ("close_all_positions", XAUUSD_ID)
ORDER = ("create_order", XAUUSD_ID, DEFAULT_ORDER)

LOCK_ACQUIRED = "[lock acquired]"
LOCK_RELEASED = "[lock released]"

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def console_lines(capsys):
    """The operator lines printed so far, without colour codes or blank lines.

    Colour codes and the blank reset lines are presentation; the text, its
    order and its position inside the critical section are what count.
    """
    out = ANSI_ESCAPE.sub("", capsys.readouterr().out)
    return [line for line in out.splitlines() if line.strip()]


def payload(action="open", direction="buy", lot="0.01/100", tp="500", sl="1000", invert="NonInvert", symbol="XAUUSD"):
    return [symbol, direction, lot, tp, sl, action, invert]


def order_rejection():
    return TLAPIOrderException({}, {"errmsg": "Not enough margin"})


def broker(balance=1000.0, open_positions=(), order_results=(9001,), close_requests_to_fill=1, failures=None):
    return FakeTradeLocker(
        balance=balance,
        instrument_ids={"XAUUSD": XAUUSD_ID, "EURUSD": EURUSD_ID},
        open_positions=open_positions,
        order_results=order_results,
        close_requests_to_fill=close_requests_to_fill,
        failures=failures,
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


def generated_webhook_path():
    """One path as ``--url generate`` makes it."""
    return generate_random_url()


LOGIN = "[login]"
SERVE = "[serve]"

# The required arguments, for the demo server; tests add the optional ones.
DEMO = ("--username", "u", "--password", "p", "--server", "s", "--env", "demo")


class Startup:
    """Runs the bot's startup with a recorded login and a recorded server start.

    The login hands back ``client``, or raises it when it is an exception, and
    the server start returns at once with the app it was given, so a test can
    send requests to the very app the bot would serve. Each prints a marker
    line, so pinned console output shows where the banners fall around them.
    """

    def __init__(self, monkeypatch, client=None):
        self.logins = []
        self.served = []
        self._monkeypatch = monkeypatch

        def tl_api(**credentials):
            self.logins.append(credentials)
            print(LOGIN)
            if isinstance(client, BaseException):
                raise client
            return client

        # uvicorn's own parameter names and defaults, keyword-only as in
        # uvicorn: a call that passes anything else is recorded in ``options``.
        def run(app, *, host="127.0.0.1", port=8000, **options):
            self.served.append({"app": app, "host": host, "port": port, "options": options})
            print(SERVE)

        monkeypatch.setattr(bot, "TLAPI", tl_api)
        monkeypatch.setattr(bot.uvicorn, "run", run)
        # Legacy registers the route on a module-level app, so a second
        # startup in the same process adds a second route. The app itself is
        # kept, so its own settings stay under test; its route list and cached
        # schema are put back after each test instead.
        monkeypatch.setattr(bot.app.router, "routes", list(bot.app.router.routes))
        monkeypatch.setattr(bot.app, "openapi_schema", None)

    def run(self, *argv):
        self._monkeypatch.setattr(sys, "argv", ["main_without_ssl.py", *argv])
        bot.main()

    @property
    def app(self):
        [served] = self.served
        return served["app"]


def serve(monkeypatch, client, *argv):
    """Start the bot on the demo arguments plus ``argv`` and return its app."""
    startup = Startup(monkeypatch, client)
    startup.run(*DEMO, *argv)
    return startup.app
