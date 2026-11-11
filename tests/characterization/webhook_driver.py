"""Sends webhook requests to the bot's app and waits for the threads they start.

Independent of where the app is built, so it is not part of the seam in
``harness``.
"""

import threading

from fastapi.testclient import TestClient

from tests.characterization.fake_tradelocker import BROKER_CALLS

# Long enough for any handler in this suite, short enough that a handler that
# hangs fails the test instead of the run.
WAIT_SECONDS = 5


def post(app, path, body=b"", **client_options):
    """POST ``body`` the way the alert sender does.

    Returns the response and the threads the request left running. A client
    used without ``with`` starts its event loop thread for this one request
    and joins it before returning, so any thread that is new afterwards was
    started by the app.
    """
    before = set(threading.enumerate())
    response = TestClient(app, **client_options).post(path, content=body)
    return response, [thread for thread in threading.enumerate() if thread not in before]


def finish(threads):
    """Wait for handler threads, and fail if one is still running."""
    for thread in threads:
        thread.join(WAIT_SECONDS)
        assert not thread.is_alive(), f"{thread.name} still running"


class GatedClient:
    """A broker client whose first broker call waits for the test.

    The wait comes before the call reaches ``fake``, so ``fake.calls`` stays
    empty until the test opens the gate: a test can look at the system while
    one handler is parked inside the critical section. ``callers`` records
    the thread of every broker call, so a test can tell which thread handled
    the signal.
    """

    def __init__(self, fake):
        self.fake = fake
        self.gate = threading.Event()
        self.entered = threading.Event()
        self._first = True
        self._first_guard = threading.Lock()
        self.callers = []

    def __getattr__(self, name):
        method = getattr(self.fake, name)
        if name not in BROKER_CALLS:
            return method

        def call(*args, **kwargs):
            self.callers.append(threading.current_thread())
            with self._first_guard:
                first, self._first = self._first, False
            if first:
                self.entered.set()
                if not self.gate.wait(WAIT_SECONDS):
                    raise AssertionError("the test never opened the gate")
            return method(*args, **kwargs)

        return call
