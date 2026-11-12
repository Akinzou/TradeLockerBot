"""``telegram_from``: the Telegram settings, both or neither (ADR 0027)."""

import pytest

from tradelocker_bot.adapters.telegram import TelegramSettings, telegram_from
from tradelocker_bot.domain.result import Err, Ok

TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


def _token_file(tmp_path, content=TOKEN.encode() + b"\n"):
    path = tmp_path / "telegram_token"
    path.write_bytes(content)
    return str(path)


@pytest.mark.parametrize("env", [{}, {"telegram_token_file": "", "telegram_chat_id": ""}])
def test_neither_setting_leaves_telegram_off(env):
    assert telegram_from(env) == Ok(None)


@pytest.mark.parametrize("chat_id", ["123456789", "-1001234567890", "@trading_alerts"])
def test_both_settings_give_the_token_and_the_chat(tmp_path, chat_id):
    env = {"telegram_token_file": _token_file(tmp_path), "telegram_chat_id": chat_id}

    assert telegram_from(env) == Ok(TelegramSettings(TOKEN, chat_id))


def test_a_chat_without_a_token_file_stops_rather_than_leaving_telegram_off(tmp_path):
    assert telegram_from({"telegram_chat_id": "123"}) == Err(
        "telegram_chat_id is set without telegram_token_file: set both, or neither")


def test_a_token_file_without_a_chat_stops_rather_than_leaving_telegram_off(tmp_path):
    assert telegram_from({"telegram_token_file": _token_file(tmp_path)}) == Err(
        "telegram_token_file is set without telegram_chat_id: set both, or neither")


def test_the_token_file_is_read_under_the_rules_of_the_password_file(tmp_path):
    env = {"telegram_token_file": _token_file(tmp_path, b""), "telegram_chat_id": "123"}

    assert telegram_from(env) == Err("telegram_token_file: the file is empty")


@pytest.mark.parametrize(
    "content",
    [
        "ABC-DEF1234ghIkl",
        "123456",
        ":ABC",
        "123456:",
        # The token becomes part of the request's path: a slash, a query or
        # an escape there would send it somewhere else.
        "123456:ABC/../../x",
        "123456:ABC?x=1",
        "123456:ABC%2F",
        "123456:ABC DEF",
        "password=123456:ABC",
    ],
)
def test_a_file_that_holds_no_bot_token_stops_without_showing_it(tmp_path, content):
    env = {"telegram_token_file": _token_file(tmp_path, content.encode()), "telegram_chat_id": "123"}

    result = telegram_from(env)

    assert result == Err("telegram_token_file: the file holds no bot token, "
                         "which is digits, a colon, then letters, digits, - and _")
    assert content not in result.error


@pytest.mark.parametrize("chat_id", ["12a", "@", "@ab", "1 2", "123\n", "+123", "--1", "@name/x"])
def test_a_chat_id_that_names_no_chat_stops(tmp_path, chat_id):
    env = {"telegram_token_file": _token_file(tmp_path), "telegram_chat_id": chat_id}

    assert telegram_from(env) == Err(
        "telegram_chat_id: expected a chat's number, such as -1001234567890, or @ and a channel's name")


def test_the_settings_never_show_the_token():
    settings = TelegramSettings(TOKEN, "123")

    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings)
