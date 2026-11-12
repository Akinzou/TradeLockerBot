"""Characterization tests for the bot's startup: settings, banners, login,
account selection, the webhook path and the server start.

The order is pinned with the login and server marker lines: settings first,
then the banners, then the account selectors as integers, then the login,
then the route and the server. A failure at one of those points leaves every
later one undone.

The image starts the bot with no arguments, so its settings come from the
environment; ``test_startup_settings.py`` pins how they are read (ADR 0018).
"""

import copy
import re

import pytest
from uvicorn.config import LOGGING_CONFIG

from tests.characterization.harness import (
    DEMO,
    DEMO_LOGIN,
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

# One segment: 24 random bytes in URL-safe base64, unpadded (ADR 0012).
GENERATED_PATH = re.compile(r"/[A-Za-z0-9_-]{32}")

# uvicorn's default log settings with the access line's request line
# replaced (ADR 0016). Spelled out rather than taken from the bot, so a
# change to the bot's settings fails here as well as in test_server_log.py,
# which pins what a real server writes with them.
LOG_CONFIG = copy.deepcopy(LOGGING_CONFIG)
LOG_CONFIG["formatters"]["access"]["fmt"] = '%(levelprefix)s %(client_addr)s - "<request line hidden>" %(status_code)s'


@pytest.fixture
def startup(monkeypatch):
    return Startup(monkeypatch, broker())


def test_a_generated_path_is_one_segment_of_32_url_safe_characters():
    # The shape only; the unit tests pin the source (ADR 0012).
    for _ in range(50):
        assert GENERATED_PATH.fullmatch(generated_webhook_path())


def test_startup_greets_logs_in_and_serves_on_every_interface_at_port_443(startup, capsys):
    startup.run(DEMO)

    assert capsys.readouterr().out == f"{GREEN}{HELLO}{RESET}\n{LOGIN}\n{SERVE}\n"
    assert startup.logins == [DEMO_LOGIN]
    assert [{k: v for k, v in s.items() if k != "app"} for s in startup.served] == [
        {"host": "0.0.0.0", "port": 443, "options": {"log_config": LOG_CONFIG}},
    ]


def test_live_environment_logs_in_to_the_live_server(startup):
    startup.run({**DEMO, "env": "live"})

    assert startup.logins == [{**DEMO_LOGIN, "environment": "https://live.tradelocker.com"}]


@pytest.mark.parametrize(
    ("selector", "login"),
    [
        ({"acc_num": "2"}, {"acc_num": 2}),
        ({"acc_id": "77"}, {"account_id": 77}),
        ({"acc_num": "0", "acc_id": "0"}, {}),
    ],
)
def test_account_selectors_reach_the_login_as_integers(startup, selector, login):
    startup.run({**DEMO, **selector})

    assert startup.logins == [{**DEMO_LOGIN, **login}]


def test_port_option_sets_the_server_port(startup):
    startup.run(DEMO, "--port", "8443")

    assert startup.served[0]["port"] == 8443


def test_generated_path_is_announced_before_the_greeting_and_served(startup, capsys):
    startup.run({**DEMO, "url": "generate"})

    out = capsys.readouterr().out
    url_banner = f"{RED}{SAVE_URL}{RESET}\n"
    assert out.startswith(url_banner)
    path, rest = out[len(url_banner):].split("\n", 1)
    assert GENERATED_PATH.fullmatch(path)
    assert rest == f"{GREEN}{HELLO}{RESET}\n{LOGIN}\n{SERVE}\n"
    assert post(startup.app, path, b"")[0].status_code == 200
    assert post(startup.app, "/strategy", b"")[0].status_code == 404


def test_custom_path_replaces_the_default(startup):
    startup.run({**DEMO, "url": "/hook"})

    assert post(startup.app, "/hook", b"")[0].status_code == 200
    assert post(startup.app, "/strategy", b"")[0].status_code == 404


@pytest.mark.parametrize("url", ["strategy", "hook/secret", "https://host/strategy", ""])
def test_a_path_without_a_leading_slash_stops_before_any_output_and_is_not_echoed(startup, capsys, url):
    # ADR 0014: such a route matched no request, so the bot looked up while
    # every alert got a 404. It now stops like any invalid argument, and the
    # error leaves the value out: it is the operator's secret path, give or
    # take a slash, and stderr goes to the same log as everything else.
    with pytest.raises(SystemExit) as exited:
        startup.run({**DEMO, "url": url})

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith("error: argument --url: must start with / or be generate")
    # No piece of the value either, such as the last segment of a path.
    assert [part for part in re.split("[/:]", url) if part and part in err] == []
    assert startup.logins == []
    assert startup.served == []


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        ({"acc_num": "two"}, "invalid literal for int"),
        ({"acc_id": "1.5"}, "invalid literal for int"),
        ({"acc_num": "2", "acc_id": "77"}, "only the account number or ID"),
    ],
)
def test_a_bad_account_selector_stops_after_the_greeting_and_before_the_login(startup, capsys, selector, message):
    with pytest.raises(ValueError, match=message):
        startup.run({**DEMO, **selector})

    assert console_lines(capsys) == HELLO_LINES
    assert startup.logins == []
    assert startup.served == []


def test_a_failed_login_raises_and_never_starts_the_server(monkeypatch, capsys):
    refused = ConnectionError("login refused")
    startup = Startup(monkeypatch, refused)

    with pytest.raises(ConnectionError) as raised:
        startup.run(DEMO)

    assert raised.value is refused
    assert console_lines(capsys) == [*HELLO_LINES, LOGIN]
    assert startup.served == []


@pytest.mark.parametrize(
    "url",
    [
        "/{zq7}",
        "/{zq7:path}",
        "/hook/{zq7}",
        "/{zq7:int}",
        "/{zq7:foo}",
        "/{zq7}/{zq7}",
        "/{987}",
        "/hook{zq7",
        "/hook}zq7",
    ],
)
def test_a_path_with_a_brace_stops_before_any_output_and_is_not_echoed(startup, capsys, url):
    # ADR 0015: `{name}` made the setting a pattern, so other paths opened
    # trades, and a pattern Starlette could not compile stopped the bot after
    # the login. Any `{` or `}` now stops it like any invalid argument, before
    # the banners, with the value left out of the error.
    with pytest.raises(SystemExit) as exited:
        startup.run({**DEMO, "url": url})

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith("error: argument --url: must not contain { or }")
    # Split on braces too, since the message has them; the names are ones the
    # usage text above it cannot contain, so a match can only be an echo.
    assert [part for part in re.split("[/:{}]", url) if part and part in err] == []
    assert startup.logins == []
    assert startup.served == []


def test_a_value_with_a_brace_and_no_leading_slash_gets_the_slash_message(startup, capsys):
    # The leading slash is checked first, so one value always gets one message.
    with pytest.raises(SystemExit) as exited:
        startup.run({**DEMO, "url": "{zq7}"})

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith("error: argument --url: must start with / or be generate")
    assert "zq7" not in err
    assert startup.logins == []
    assert startup.served == []


def test_help_lists_every_option_and_exits_cleanly(startup, capsys):
    with pytest.raises(SystemExit) as exited:
        startup.run({}, "--help")

    assert exited.value.code == 0
    # The usage paragraph, with argparse's terminal-width wrapping undone: it
    # names every option, which ones are required and the allowed environments.
    # The program name is left out: from Python 3.14 argparse derives it from
    # how the interpreter was started, which under pytest is not the bot.
    out = capsys.readouterr().out
    usage = " ".join(out.split("\n\n")[0].split())
    assert usage.startswith("usage: ")
    assert usage[usage.index(" [-h] "):] == (
        " [-h] --username USERNAME --server SERVER "
        "--env {live,demo} [--url URL] [--acc_num ACC_NUM] [--acc_id ACC_ID] [--port PORT]"
    )
    # Where the settings come from, wrapping undone as above.
    text = " ".join(out.split())
    assert "set in the environment variable of the same name" in text
    assert "password environment variable" in text
    assert startup.logins == []
