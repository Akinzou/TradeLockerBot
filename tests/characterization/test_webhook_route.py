"""Characterization tests for the webhook route, from the HTTP request to the
handler thread.

The app under test is the one the startup hands to the server, built with the
default arguments unless a test names its own path, so these pins cover the
route as deployed: its path, its
answer, how the body becomes payload lines, one thread per request, one lock
for every request, and an exception that ends the thread rather than the
response.
"""

import threading

import pytest
from fastapi.testclient import TestClient
from tradelocker.exceptions import TLAPIException

from tests.characterization.harness import (
    BALANCE,
    CLOSE,
    LOOKUP,
    ORDER,
    POSITIONS,
    XAUUSD_ID,
    broker,
    console_lines,
    payload,
    serve,
)
from tests.characterization.webhook_driver import WAIT_SECONDS, GatedClient, finish, post

SIGNAL = "\n".join(payload()).encode()
OPEN_CALLS = [BALANCE, LOOKUP, POSITIONS, ORDER]


@pytest.fixture
def gated(monkeypatch):
    """A served app whose first broker call is parked until the test opens it.

    The gate is opened and the handlers joined on teardown too: a failed
    assertion must not leave a handler holding the shared lock, or every
    later test that needs it waits behind it.
    """
    client = GatedClient(broker(order_results=(9001, 9002)))
    before = set(threading.enumerate())
    yield client, serve(monkeypatch, client)
    client.gate.set()
    finish([thread for thread in threading.enumerate() if thread not in before])


def test_the_answer_is_200_with_a_null_body_before_the_signal_is_handled(gated):
    client, app = gated

    response, threads = post(app, "/strategy", SIGNAL)

    assert (response.status_code, response.content) == (200, b"null")
    assert response.headers["content-type"] == "application/json"
    assert client.fake.calls == []
    assert len(threads) == 1 and threads[0].is_alive()
    client.gate.set()
    finish(threads)
    assert client.fake.calls == OPEN_CALLS


def test_every_request_gets_its_own_thread_and_all_share_one_lock(gated):
    client, app = gated
    _, first = post(app, "/strategy", SIGNAL)
    assert client.entered.wait(WAIT_SECONDS)

    _, second = post(app, "/strategy", SIGNAL)
    # The second handler would read the balance at once with a lock of its own;
    # with the shared one it waits behind the first, parked at the gate.
    # A wait cannot prove a negative; one second is enough for an unblocked
    # thread to reach its first call, and a slower one only lets a broken lock
    # pass this time, never fails a correct one.
    second[0].join(1)

    assert len(first) == len(second) == 1 and first != second
    assert second[0].is_alive()
    assert client.fake.calls == []
    client.gate.set()
    finish(first + second)
    assert client.fake.calls == OPEN_CALLS + OPEN_CALLS


@pytest.mark.parametrize(
    "separator",
    ["\n", "\r\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
def test_the_body_is_decoded_as_utf8_and_split_at_every_line_boundary(monkeypatch, separator):
    fake = broker()
    app = serve(monkeypatch, fake)

    _, threads = post(app, "/strategy", (separator.join(payload()) + separator).encode())
    finish(threads)

    assert fake.calls == OPEN_CALLS


def test_an_empty_body_is_rejected_as_a_missing_symbol(monkeypatch, capsys):
    fake = broker()
    app = serve(monkeypatch, fake)
    capsys.readouterr()

    response, threads = post(app, "/strategy", b"")
    finish(threads)

    assert response.status_code == 200
    assert console_lines(capsys) == ["Signal rejected: line 1 (symbol) is missing, expected an instrument name"]
    assert fake.calls == []


def test_a_body_that_is_not_utf8_fails_the_request_and_starts_no_thread(monkeypatch, capsys):
    fake = broker()
    app = serve(monkeypatch, fake)
    capsys.readouterr()

    response, threads = post(app, "/strategy", SIGNAL + b"\xff", raise_server_exceptions=False)

    assert (response.status_code, response.content) == (500, b"Internal Server Error")
    assert threads == []
    assert capsys.readouterr().out == ""
    assert fake.calls == []


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/strategy", 405), ("PUT", "/strategy", 405), ("POST", "/", 404), ("POST", "/Strategy", 404),
     ("POST", "/strategy/x", 404)],
)
def test_only_post_on_the_exact_path_reaches_the_handler(monkeypatch, method, path, status):
    fake = broker()
    app = serve(monkeypatch, fake)
    before = set(threading.enumerate())

    response = TestClient(app, follow_redirects=False).request(method, path, content=SIGNAL)

    assert response.status_code == status
    assert set(threading.enumerate()) <= before
    assert fake.calls == []


def test_a_trailing_slash_is_redirected_to_the_path_without_handling(monkeypatch):
    # Starlette's slash redirect: 307 keeps the method and body, so a sender
    # that follows redirects delivers the alert on its second request.
    fake = broker()
    app = serve(monkeypatch, fake)

    response = TestClient(app, follow_redirects=False).post("/strategy/", content=SIGNAL)

    assert response.status_code == 307
    assert response.headers["location"] == "http://testserver/strategy"
    assert fake.calls == []


def test_a_broker_failure_ends_the_handler_thread_with_the_clients_exception(monkeypatch):
    failure = TLAPIException({}, {"errmsg": "Service unavailable"})
    client = GatedClient(broker(failures={("get_all_positions", 1): failure}))
    client.gate.set()
    raised = []
    monkeypatch.setattr(threading, "excepthook", lambda hook: raised.append((hook.exc_value, hook.thread)))
    app = serve(monkeypatch, client)

    response, threads = post(app, "/strategy", SIGNAL)
    finish(threads)

    assert response.status_code == 200
    [(exception, thread)] = raised
    assert exception is failure
    # The thread that made the broker calls, not some other background thread.
    assert set(client.callers) == {thread}
    assert thread is not threading.current_thread()


def test_a_close_signal_is_handled_through_the_route(monkeypatch):
    fake = broker(open_positions=[XAUUSD_ID])
    app = serve(monkeypatch, fake)

    _, threads = post(app, "/strategy", "\n".join(payload(action="close")).encode())
    finish(threads)

    assert fake.calls == [LOOKUP, POSITIONS, CLOSE, POSITIONS]


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"])
def test_no_api_docs_are_served_so_no_page_names_the_webhook_path(monkeypatch, path):
    # ADR 0011: the OpenAPI schema named the webhook path, the endpoint's only
    # protection. Each former docs address now answers exactly like an
    # address the app never had, so a scan cannot tell it was ever there.
    fake = broker()
    app = serve(monkeypatch, fake, "--url", "/hook/secret")
    client = TestClient(app, follow_redirects=False)
    unknown = client.get("/no-such-page")

    response = client.get(path)

    assert (response.status_code, response.content) == (404, b'{"detail":"Not Found"}')
    assert response.headers == unknown.headers
    assert fake.calls == []
