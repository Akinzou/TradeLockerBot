"""``TelegramChat`` against a server on this machine, through the real
``urllib`` (ADR 0027).

The bot token is part of every request's path, so the pins look for it in
every failure the chat returns and in everything printed, for each way a
send can fail: an error answer, a flood answer, a server error, an answer
that is not Telegram's, a refused connection and a timeout.
"""

import json
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tradelocker_bot.adapters.notifier import SendFailure
from tradelocker_bot.adapters.telegram import MAX_TEXT_CHARACTERS, TelegramChat, TelegramSettings
from tradelocker_bot.domain.result import Err, Ok

TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
SENT = {"ok": True, "result": {"message_id": 1}}


class TelegramServer:
    """Answers each request with the next of ``answers``, a status and a
    body, and records the requests; a body of ``None`` hangs past any
    timeout the tests use."""

    def __init__(self, *answers):
        self.requests = []
        self._answers = list(answers)
        self._release = threading.Event()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                server.requests.append({"path": self.path, "headers": dict(self.headers),
                                        "body": self.rfile.read(length)})
                status, body = server._answers.pop(0)
                if body is None:
                    server._release.wait(5)
                    return
                content = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._release.set()
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def telegram():
    servers = []

    def start(*answers):
        servers.append(TelegramServer(*answers))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def _chat(api, chat_id="-1001234567890", timeout=5.0):
    return TelegramChat(TelegramSettings(TOKEN, chat_id), urllib.request.urlopen, api=api, timeout=timeout)


def test_a_message_is_posted_as_plain_text_to_the_bots_send_message(telegram):
    server = telegram((200, SENT))

    assert _chat(server.api).send("Signal rejected: line 2 (direction) is 'long'") == Ok(None)

    [request] = server.requests
    assert request["path"] == f"/bot{TOKEN}/sendMessage"
    assert request["headers"]["Content-Type"] == "application/json"
    # No parse_mode: the lines quote webhook and broker text, which Markdown
    # or HTML would read as markup, or refuse.
    assert json.loads(request["body"]) == {
        "chat_id": -1001234567890,
        "text": "Signal rejected: line 2 (direction) is 'long'",
        "link_preview_options": {"is_disabled": True},
    }


def test_a_channel_is_named_as_written(telegram):
    server = telegram((200, SENT))

    _chat(server.api, chat_id="@trading_alerts").send("x")

    assert json.loads(server.requests[0]["body"])["chat_id"] == "@trading_alerts"


def test_a_text_longer_than_telegram_takes_is_cut_rather_than_refused(telegram):
    server = telegram((200, SENT))

    _chat(server.api).send("x" * (MAX_TEXT_CHARACTERS + 10))

    assert json.loads(server.requests[0]["body"])["text"] == "x" * MAX_TEXT_CHARACTERS


@pytest.mark.parametrize(
    ("answer", "failure"),
    [
        # A setting is wrong: the same request gets the same answer.
        ((403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}),
         SendFailure("HTTP 403, 'Forbidden: bot was blocked by the user'", retry=False)),
        ((400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}),
         SendFailure("HTTP 400, 'Bad Request: chat not found'", retry=False)),
        ((401, {"ok": False, "error_code": 401}), SendFailure("HTTP 401", retry=False)),
        # Telegram's text, cut and escaped like the broker's.
        ((400, {"ok": False, "description": "\x1b[92m" + "d" * 300}),
         SendFailure(f"HTTP 400, '\\x1b[92m{'d' * 155}'... (305 characters)", retry=False)),
        # Telegram's own pace: wait as long as it says.
        ((429, {"ok": False, "description": "Too Many Requests: retry after 7", "parameters": {"retry_after": 7}}),
         SendFailure("HTTP 429, 'Too Many Requests: retry after 7'", retry=True, retry_after=7.0)),
        ((429, {"ok": False}), SendFailure("HTTP 429", retry=True)),
        ((502, b"<html>Bad Gateway</html>"), SendFailure("HTTP 502", retry=True)),
        ((500, {"ok": False, "description": "Internal Server Error"}),
         SendFailure("HTTP 500, 'Internal Server Error'", retry=True)),
        # An answer that is not Telegram's, from a proxy, say.
        ((200, b"<html>Welcome</html>"), SendFailure("HTTP 200, an answer that is not Telegram's", retry=True)),
        ((200, {"ok": False}), SendFailure("HTTP 200", retry=True)),
        ((200, [1]), SendFailure("HTTP 200, an answer that is not Telegram's", retry=True)),
        ((429, {"ok": False, "parameters": {"retry_after": "soon"}}), SendFailure("HTTP 429", retry=True)),
        # Passed on as given: the notifier decides which waits it keeps.
        ((429, {"ok": False, "parameters": {"retry_after": -1}}),
         SendFailure("HTTP 429", retry=True, retry_after=-1.0)),
    ],
)
def test_an_answer_that_is_not_a_sent_message_is_a_failure_that_says_whether_to_try_again(
        telegram, capsys, answer, failure):
    server = telegram(answer)

    result = _chat(server.api).send("x")

    assert result == Err(failure)
    assert TOKEN not in repr(result)
    assert TOKEN not in "".join(capsys.readouterr())


def _closed_port():
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        return unused.getsockname()[1]


def test_no_server_is_a_failure_to_try_again_without_the_token(capsys):
    result = _chat(f"http://127.0.0.1:{_closed_port()}").send("x")

    assert result == Err(SendFailure("no answer (ConnectionRefusedError)", retry=True))
    assert TOKEN not in "".join(capsys.readouterr())


def test_a_server_that_does_not_answer_in_time_is_a_failure_to_try_again(telegram, capsys):
    server = telegram((200, None))

    result = _chat(server.api, timeout=0.2).send("x")

    assert result == Err(SendFailure("no answer (TimeoutError)", retry=True))
    assert TOKEN not in "".join(capsys.readouterr())


def test_any_other_failure_of_the_transport_is_returned_by_its_type_alone():
    def urlopen(request, timeout):
        raise ValueError(f"unknown url type: {request.full_url}")

    result = TelegramChat(TelegramSettings(TOKEN, "1"), urlopen).send("x")

    assert result == Err(SendFailure("no answer (ValueError)", retry=True))
