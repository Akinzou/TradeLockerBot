"""Characterization tests for the Telegram settings at startup (ADR 0027).

``urlopen`` is replaced where the composition root takes it, so no test
reaches Telegram; ``test_telegram_chat.py`` runs the real one against a
server on this machine.
"""

import io
import json
import threading

import pytest

from tests.characterization.harness import DEMO, Startup, broker, console_lines, payload
from tests.characterization.webhook_driver import finish, post
from tradelocker_bot import composition_root

TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
WAIT_SECONDS = 5
NOTIFIER = "telegram-notifier"


class Answer(io.BytesIO):
    status = 200


class Telegram:
    """``urlopen`` for the composition root: records each message and
    answers it as sent, after ``gate`` opens."""

    def __init__(self):
        self.messages = []
        self.urls = []
        self.gate = threading.Event()
        self.gate.set()
        self._received = threading.Condition()

    def urlopen(self, request, timeout):
        with self._received:
            self.urls.append(request.full_url)
            self.messages.append(json.loads(request.data)["text"])
            self._received.notify_all()
        assert self.gate.wait(WAIT_SECONDS)
        return Answer(b'{"ok": true, "result": {}}')

    def wait_for(self, count):
        with self._received:
            assert self._received.wait_for(lambda: len(self.messages) >= count, WAIT_SECONDS), self.messages
        return self.messages


@pytest.fixture
def telegram(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr(composition_root, "urlopen", fake.urlopen)
    yield fake
    fake.gate.set()


def _with_telegram(tmp_path, **environ):
    path = tmp_path / "telegram_token"
    path.write_bytes(TOKEN.encode() + b"\n")
    return {**DEMO, "telegram_token_file": str(path), "telegram_chat_id": "-1001234567890", **environ}


def _notifiers():
    return sum(thread.name == NOTIFIER for thread in threading.enumerate())


def test_without_the_settings_nothing_is_sent_and_no_thread_starts(monkeypatch, capsys, telegram):
    before = _notifiers()

    Startup(monkeypatch, broker()).run(DEMO)

    assert _notifiers() == before
    assert telegram.messages == []
    assert "Telegram" not in capsys.readouterr().out


def test_with_the_settings_the_account_line_is_sent_once_logged_in(monkeypatch, capsys, telegram, tmp_path):
    before = _notifiers()
    startup = Startup(monkeypatch, broker())

    startup.run(_with_telegram(tmp_path))

    assert telegram.wait_for(1) == ["Logged in: acc_id 76, acc_num 1"]
    assert telegram.urls == [f"https://api.telegram.org/bot{TOKEN}/sendMessage"]
    assert _notifiers() == before + 1
    out, err = capsys.readouterr()
    assert "Telegram: on; the account line and every red line also go to the chat" in out
    assert TOKEN not in out + err


def test_a_red_line_from_a_signal_is_sent_to_the_chat(monkeypatch, capsys, telegram, tmp_path):
    startup = Startup(monkeypatch, broker())
    startup.run(_with_telegram(tmp_path))

    _, threads = post(startup.app, "/strategy", "\n".join(payload(direction="long")).encode())
    finish(threads)

    assert telegram.wait_for(2)[1] == "Signal rejected: line 2 (direction) is 'long', expected buy or sell"


def test_a_signal_does_not_wait_for_a_telegram_that_does_not_answer(monkeypatch, capsys, telegram, tmp_path):
    telegram.gate.clear()
    startup = Startup(monkeypatch, broker())
    startup.run(_with_telegram(tmp_path))
    telegram.wait_for(1)

    _, threads = post(startup.app, "/strategy", "\n".join(payload()).encode())
    finish(threads)

    assert "Order placed successfully, order ID: 9001" in console_lines(capsys)


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"telegram_token_file": ""},
         "error: telegram_chat_id is set without telegram_token_file: set both, or neither"),
        ({"telegram_chat_id": ""}, "error: telegram_token_file is set without telegram_chat_id: set both, or neither"),
        ({"telegram_chat_id": "chat"},
         "error: telegram_chat_id: expected a chat's number, such as -1001234567890, or @ and a channel's name"),
        ({"telegram_token_file": "missing"},
         "error: telegram_token_file: the file cannot be read (No such file or directory)"),
    ],
)
def test_settings_that_name_no_chat_stop_before_any_output(monkeypatch, capsys, telegram, tmp_path, environ, message):
    startup = Startup(monkeypatch, broker())

    with pytest.raises(SystemExit) as exited:
        startup.run(_with_telegram(tmp_path, **environ))

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith(message)
    assert TOKEN not in err
    assert startup.logins == []
    assert telegram.messages == []
