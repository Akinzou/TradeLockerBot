"""Characterization tests for the bot's startup: arguments, banners, login,
account selection, the webhook path and the server start.

The order is pinned with the login and server marker lines: arguments first,
then the banners, then the account selectors as integers, then the login,
then the route and the server. A failure at one of those points leaves every
later one undone.
"""

import re

import pytest

from tests.characterization.harness import (
    DEMO,
    LOGIN,
    SERVE,
    Startup,
    broker,
    console_lines,
    generated_webhook_path,
)
from tests.characterization.webhook_driver import post

GREEN = "\x1b[92m"
RED = "\x1b[91m"
RESET = "\x1b[0m"

HELLO = r"""
 _____              _      _               _             ____        _
|_   _| __ __ _  __| | ___| |    ___   ___| | _____ _ __| __ )  ___ | |_
  | || '__/ _` |/ _` |/ _ \ |   / _ \ / __| |/ / _ \ '__|  _ \ / _ \| __|
  | || | | (_| | (_| |  __/ |__| (_) | (__|   <  __/ |  | |_) | (_) | |_
  |_||_|  \__,_|\__,_|\___|_____\___/ \___|_|\_\___|_|  |____/ \___/ \__|
"""

SAVE_URL = r"""
                                  _
 ___  __ ___   _____   _   _ _ __| |
/ __|/ _` \ \ / / _ \ | | | | '__| |
\__ \ (_| |\ V /  __/ | |_| | |  | |
|___/\__,_| \_/ \___|  \__,_|_|  |_|
"""

HELLO_LINES = [line for line in HELLO.splitlines() if line.strip()]

DEMO_LOGIN = {"environment": "https://demo.tradelocker.com", "username": "u", "password": "p", "server": "s"}
# One segment: 24 random bytes in URL-safe base64, unpadded (ADR 0012).
GENERATED_PATH = re.compile(r"/[A-Za-z0-9_-]{32}")


@pytest.fixture
def startup(monkeypatch):
    return Startup(monkeypatch, broker())


def test_a_generated_path_is_one_segment_of_32_url_safe_characters():
    # The shape only; the unit tests pin the source (ADR 0012).
    for _ in range(50):
        assert GENERATED_PATH.fullmatch(generated_webhook_path())


def test_startup_greets_logs_in_and_serves_on_every_interface_at_port_443(startup, capsys):
    startup.run(*DEMO)

    assert capsys.readouterr().out == f"{GREEN}{HELLO}{RESET}\n{LOGIN}\n{SERVE}\n"
    assert startup.logins == [DEMO_LOGIN]
    assert [{k: v for k, v in s.items() if k != "app"} for s in startup.served] == [
        {"host": "0.0.0.0", "port": 443, "options": {}},
    ]


def test_live_environment_logs_in_to_the_live_server(startup):
    startup.run("--username", "u", "--password", "p", "--server", "s", "--env", "live")

    assert startup.logins == [{**DEMO_LOGIN, "environment": "https://live.tradelocker.com"}]


@pytest.mark.parametrize(
    ("selector", "login"),
    [
        (("--acc_num", "2"), {"acc_num": 2}),
        (("--acc_id", "77"), {"account_id": 77}),
        (("--acc_num", "0", "--acc_id", "0"), {}),
    ],
)
def test_account_selectors_reach_the_login_as_integers(startup, selector, login):
    startup.run(*DEMO, *selector)

    assert startup.logins == [{**DEMO_LOGIN, **login}]


def test_port_option_sets_the_server_port(startup):
    startup.run(*DEMO, "--port", "8443")

    assert startup.served[0]["port"] == 8443


def test_generated_path_is_announced_before_the_greeting_and_served(startup, capsys):
    startup.run(*DEMO, "--url", "generate")

    out = capsys.readouterr().out
    url_banner = f"{RED}{SAVE_URL}{RESET}\n"
    assert out.startswith(url_banner)
    path, rest = out[len(url_banner):].split("\n", 1)
    assert GENERATED_PATH.fullmatch(path)
    assert rest == f"{GREEN}{HELLO}{RESET}\n{LOGIN}\n{SERVE}\n"
    assert post(startup.app, path, b"")[0].status_code == 200
    assert post(startup.app, "/strategy", b"")[0].status_code == 404


def test_custom_path_replaces_the_default(startup):
    startup.run(*DEMO, "--url", "/hook")

    assert post(startup.app, "/hook", b"")[0].status_code == 200
    assert post(startup.app, "/strategy", b"")[0].status_code == 404


def test_a_path_without_a_leading_slash_starts_but_is_never_reachable(startup):
    # Known defect: the route is registered as "strategy", and no request path
    # lacks the leading slash, so every alert gets a 404 while the bot looks up.
    startup.run(*DEMO, "--url", "strategy")

    assert startup.served
    assert post(startup.app, "/strategy", b"")[0].status_code == 404


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        (("--acc_num", "two"), "invalid literal for int"),
        (("--acc_id", "1.5"), "invalid literal for int"),
        (("--acc_num", "2", "--acc_id", "77"), "only the account number or ID"),
    ],
)
def test_a_bad_account_selector_stops_after_the_greeting_and_before_the_login(startup, capsys, selector, message):
    with pytest.raises(ValueError, match=message):
        startup.run(*DEMO, *selector)

    assert console_lines(capsys) == HELLO_LINES
    assert startup.logins == []
    assert startup.served == []


def test_a_failed_login_raises_and_never_starts_the_server(monkeypatch, capsys):
    refused = ConnectionError("login refused")
    startup = Startup(monkeypatch, refused)

    with pytest.raises(ConnectionError) as raised:
        startup.run(*DEMO)

    assert raised.value is refused
    assert console_lines(capsys) == [*HELLO_LINES, LOGIN]
    assert startup.served == []


@pytest.mark.parametrize(("url", "error"), [("/{x:foo}", AssertionError), ("/{x}/{x}", ValueError)])
def test_a_brace_pattern_starlette_cannot_compile_stops_after_the_login(startup, url, error):
    # Known defect: the route is built after the login, so a pattern with an
    # unknown convertor or a repeated name stops the bot with a traceback once
    # it has already logged in to the account.
    with pytest.raises(error):
        startup.run(*DEMO, "--url", url)

    assert startup.logins == [DEMO_LOGIN]
    assert startup.served == []


@pytest.mark.parametrize(
    "argv",
    [
        ("--username", "u", "--password", "p", "--server", "s", "--env", "paper"),
        ("--username", "u", "--server", "s", "--env", "demo"),
        (*DEMO, "--port", "https"),
    ],
)
def test_invalid_arguments_exit_with_status_2_before_any_output(startup, capsys, argv):
    with pytest.raises(SystemExit) as exited:
        startup.run(*argv)

    assert exited.value.code == 2
    assert capsys.readouterr().out == ""
    assert startup.logins == []


def test_help_lists_every_option_and_exits_cleanly(startup, capsys):
    with pytest.raises(SystemExit) as exited:
        startup.run("--help")

    assert exited.value.code == 0
    # The usage paragraph, with argparse's terminal-width wrapping undone: it
    # names every option, which ones are required and the allowed environments.
    # The program name is left out: from Python 3.14 argparse derives it from
    # how the interpreter was started, which under pytest is not the bot.
    usage = " ".join(capsys.readouterr().out.split("\n\n")[0].split())
    assert usage.startswith("usage: ")
    assert usage[usage.index(" [-h] "):] == (
        " [-h] --username USERNAME --password PASSWORD --server SERVER "
        "--env {live,demo} [--url URL] [--acc_num ACC_NUM] [--acc_id ACC_ID] [--port PORT]"
    )
    assert startup.logins == []
