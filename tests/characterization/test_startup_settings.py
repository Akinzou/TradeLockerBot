"""Characterization tests for where the startup reads its settings from.

The image starts the bot with no arguments, so every setting comes from its
environment variables; an option on the command line wins over its variable,
and the password is read only from the environment (ADR 0018). The image's
shell used to split, expand and glob these values and put them all in the
host's process list.
"""

import pytest

from tests.characterization.harness import DEMO, DEMO_LOGIN, Startup, broker
from tests.characterization.webhook_driver import post


@pytest.fixture
def startup(monkeypatch):
    return Startup(monkeypatch, broker())


def _without(name):
    return {key: value for key, value in DEMO.items() if key != name}


@pytest.mark.parametrize(
    ("environ", "argv"),
    [
        ({**DEMO, "env": "paper"}, ()),
        # The image's shell no longer trims a value, so neither is trimmed here.
        ({**DEMO, "env": "demo "}, ()),
        (_without("username"), ()),
        (_without("server"), ()),
        (_without("env"), ()),
        # An empty variable is not a value: the shell used to drop it, which
        # left the option without one.
        ({**DEMO, "username": ""}, ()),
        ({**DEMO, "server": ""}, ()),
        (DEMO, ("--port", "https")),
        (DEMO, ("--username", "")),
    ],
)
def test_invalid_settings_exit_with_status_2_before_any_output(startup, capsys, environ, argv):
    with pytest.raises(SystemExit) as exited:
        startup.run(environ, *argv)

    assert exited.value.code == 2
    assert capsys.readouterr().out == ""
    assert startup.logins == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        # What the image's unquoted shell split, expanded or globbed, or read
        # as an option of its own (ADR 0018).
        ("password", "p a s s"),
        ("password", "p$HOME"),
        ("password", "p*"),
        ("password", "p;exit 3"),
        ("password", "p'\"`"),
        ("password", " p "),
        ("password", "-p"),
        ("password", "--env=live"),
        ("username", "u s"),
        ("username", "-u"),
        ("username", "--u=x"),
        ("server", "s*"),
        ("server", "-s"),
    ],
)
def test_each_credential_reaches_the_login_exactly_as_set(startup, name, value):
    startup.run({**DEMO, name: value})

    assert startup.logins == [{**DEMO_LOGIN, name: value}]


def test_an_option_on_the_command_line_wins_over_its_environment_variable(startup):
    startup.run({**DEMO, "env": "live", "url": "/zq7env"}, "--env", "demo", "--url", "/zq7flag")

    assert startup.logins == [DEMO_LOGIN]
    assert post(startup.app, "/zq7flag", b"")[0].status_code == 200
    assert post(startup.app, "/zq7env", b"")[0].status_code == 404


def test_a_variable_an_option_replaces_is_not_checked(startup):
    # Replaced means unread: a bad value there cannot stop the bot.
    startup.run({**DEMO, "env": "paper", "url": "zq7", "username": ""},
                "--env", "demo", "--url", "/zq7flag", "--username", "u")

    assert startup.logins == [DEMO_LOGIN]
    assert post(startup.app, "/zq7flag", b"")[0].status_code == 200


@pytest.mark.parametrize(
    ("environ", "argv", "login"),
    [
        ({"acc_num": "2"}, ("--acc_id", "77"), {"account_id": 77}),
        ({"acc_id": "77"}, ("--acc_num", "2"), {"acc_num": 2}),
    ],
)
def test_an_account_selector_on_the_command_line_replaces_both_variables(startup, environ, argv, login):
    # The two exclude each other, so one given here stands for the pair.
    startup.run({**DEMO, **environ}, *argv)

    assert startup.logins == [{**DEMO_LOGIN, **login}]


def test_help_ignores_the_environment(startup, capsys):
    # The operator whose bot stops on a bad variable needs the help most.
    with pytest.raises(SystemExit) as exited:
        startup.run({**DEMO, "env": "paper", "url": "zq7"}, "--help")

    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith("usage: ")


@pytest.mark.parametrize("environ", [_without("password"), {**DEMO, "password": ""}])
def test_a_missing_or_empty_password_stops_before_any_output(startup, capsys, environ):
    with pytest.raises(SystemExit) as exited:
        startup.run(environ)

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith("error: the password environment variable is not set or is empty")
    assert startup.logins == []
    assert startup.served == []


REFUSED = "error: argument --password: set the password environment variable instead"
UNSHOWN = "error: unrecognized arguments, not shown: one may be the password"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--password", "zq7pw"), REFUSED),
        (("--password=zq7pw",), REFUSED),
        # argparse prints an unknown or ambiguous argument in full, so a
        # misspelt or shortened option would put the password in the log.
        (("--pass", "zq7pw"), UNSHOWN),
        (("--p=zq7pw",), UNSHOWN),
        (("--passwd=zq7pw",), UNSHOWN),
        (("--passwd", "zq7pw"), UNSHOWN),
        (("zq7pw",), UNSHOWN),
    ],
)
def test_a_password_on_the_command_line_stops_the_bot_and_is_not_echoed(startup, capsys, argv, message):
    # The process list shows the command line to every user of the host, so
    # the option is refused rather than read.
    with pytest.raises(SystemExit) as exited:
        startup.run(DEMO, *argv)

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith(message)
    assert "zq7pw" not in err
    assert startup.logins == []
    assert startup.served == []
