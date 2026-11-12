"""Characterization tests for what the server writes per request, through a
real uvicorn server.

Every other startup pin replaces ``uvicorn.run``. Here the options the bot
hands it go to a real uvicorn server on a loopback port, so the lines pinned
are the ones the container's log gets: one access line per request, with the
client and the status but not the request line, which carries the secret
webhook path (ADR 0016).
"""

import http.client
import logging
import re
import socket
import threading
import time

import pytest
import uvicorn

from tests.characterization.harness import ANSI_ESCAPE, DEMO, Startup, broker
from tests.characterization.webhook_driver import WAIT_SECONDS, finish

# Letters no banner, console line or uvicorn message contains, so finding them
# anywhere in the output means the path leaked.
SECRET = "/zq7hook"
# Searched for rather than matched from the start of a line: a handler
# thread's `print` writes its text and its newline separately, so an access
# line written in between lands after that text, on the same line.
ACCESS_LINE = re.compile(r'INFO: +127\.0\.0\.1:\d+ - "<request line hidden>" (\d{3} .+)$')
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture
def uvicorn_loggers():
    """Restores the loggers uvicorn's ``Config`` reconfigures.

    Its handlers hold the streams captured for this test, so a later test
    that logs through them would write into a closed capture.
    """
    loggers = [logging.getLogger(name) for name in UVICORN_LOGGERS]
    saved = [(lg.handlers[:], lg.filters[:], lg.level, lg.propagate, lg.disabled) for lg in loggers]
    yield
    for lg, (handlers, filters, level, propagate, disabled) in zip(loggers, saved):
        lg.handlers[:], lg.filters[:] = handlers, filters
        lg.level, lg.propagate, lg.disabled = level, propagate, disabled


def serve_for_real(served, requests, use_colors):
    """Serve ``served["app"]`` with the bot's own uvicorn options, send each
    ``(method, path, body)`` in ``requests``, stop the server and wait for
    every thread the requests started. Returns the statuses.

    The host and port the bot asks for are replaced by a loopback socket:
    they decide where the server listens, not what it writes. ``use_colors``
    stands in for a terminal: uvicorn colours its lines when stdout is one,
    as with the README's `docker run -t`, and the test's capture is not.
    """
    config = uvicorn.Config(served["app"], use_colors=use_colors, **served["options"])
    server = uvicorn.Server(config)
    before = set(threading.enumerate())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
        thread.start()
        try:
            deadline = time.monotonic() + WAIT_SECONDS
            while not server.started:
                assert time.monotonic() < deadline, "uvicorn never started"
                time.sleep(0.01)
            statuses = [send(sock.getsockname()[1], *request) for request in requests]
        finally:
            server.should_exit = True
            thread.join(WAIT_SECONDS)
    finish([t for t in threading.enumerate() if t not in before])
    return statuses


def send(port, method, path, body):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=WAIT_SECONDS)
    try:
        connection.request(method, path, body=body)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


@pytest.mark.parametrize("use_colors", [False, True], ids=["plain", "coloured"])
def test_each_request_logs_its_client_and_status_but_never_the_path(monkeypatch, capsys, uvicorn_loggers, use_colors):
    startup = Startup(monkeypatch, broker())
    startup.run({**DEMO, "url": SECRET})
    [served] = startup.served
    capsys.readouterr()

    statuses = serve_for_real(served, [
        ("POST", SECRET, b""),
        ("POST", SECRET + "?zq7=zq7", b""),
        ("POST", SECRET + "x", b""),
        ("GET", SECRET, None),
        # Not UTF-8: decoding it raises inside the app, so uvicorn logs the
        # traceback, and that must not name the path either.
        ("POST", SECRET, b"\xff"),
    ], use_colors)

    out, err = capsys.readouterr()
    assert statuses == [200, 200, 404, 405, 500]
    # The handler's own lines are always coloured; uvicorn's only with colours on.
    assert any(line.startswith("\x1b[32mINFO") for line in out.splitlines()) == use_colors
    lines = ANSI_ESCAPE.sub("", out).splitlines()
    assert [m.group(1) for m in map(ACCESS_LINE.search, lines) if m] == [
        "200 OK", "200 OK", "404 Not Found", "405 Method Not Allowed", "500 Internal Server Error",
    ]
    assert "Exception in ASGI application" in err
    assert "zq7" not in out + err
