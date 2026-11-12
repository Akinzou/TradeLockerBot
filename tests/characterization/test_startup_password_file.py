"""Characterization tests for the password read from a file (ADR 0024).

``password_file`` names a file that holds the password, such as a Docker or
Compose secret, so the password stays out of the container's environment,
which ``docker inspect`` shows. It is the other way to set the password, not
a second one: exactly one of ``password_file`` and ``password`` must be set.

Every file is written as bytes: text mode would turn ``\\n`` into ``\\r\\n``
on Windows and hide what the bot does with each line ending.
"""

import pytest

from tests.characterization.harness import DEMO, DEMO_LOGIN, Startup, broker

# In every refused file, so a test can tell the content never reached the log.
MARKER = "zq7pw"


@pytest.fixture
def startup(monkeypatch):
    return Startup(monkeypatch, broker())


def _with_file(tmp_path, content, **environ):
    path = tmp_path / "password"
    path.write_bytes(content)
    without_password = {key: value for key, value in DEMO.items() if key != "password"}
    return {**without_password, "password_file": str(path), **environ}


@pytest.mark.parametrize(
    ("content", "password"),
    [
        (b"p", "p"),
        # One line ending, as `echo` and most editors leave it, is not part
        # of the password; nothing else is trimmed (ADR 0018).
        (b"p\n", "p"),
        (b"p\r\n", "p"),
        (b"p\r", "p"),
        (b" p a $HOME * ", " p a $HOME * "),
        (b" p \n", " p "),
        (b"p\t", "p\t"),
        ("pässwörd\n".encode(), "pässwörd"),
        (b"p" * 1024, "p" * 1024),
    ],
)
def test_the_files_one_line_reaches_the_login_exactly_as_written(startup, tmp_path, content, password):
    startup.run(_with_file(tmp_path, content))

    assert startup.logins == [{**DEMO_LOGIN, "password": password}]


def test_an_empty_password_file_variable_counts_as_not_set(startup):
    # A Compose file that names `${PASSWORD_FILE}` sets it empty when the
    # host leaves it unset, so it cannot clash with the password variable.
    startup.run({**DEMO, "password_file": ""})

    assert startup.logins == [DEMO_LOGIN]


def test_an_empty_password_variable_beside_a_file_counts_as_not_set(startup, tmp_path):
    startup.run(_with_file(tmp_path, b"p", password=""))

    assert startup.logins == [{**DEMO_LOGIN, "password": "p"}]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "error: password_file: the file is empty"),
        (b"\n", "error: password_file: the file is empty"),
        (b"\r\n", "error: password_file: the file is empty"),
        # An env file, say, rather than a secret: every line of it would
        # otherwise reach the broker as one password.
        (b"password=" + MARKER.encode() + b"\nserver=s\n", "error: password_file: the file holds more than one line"),
        (MARKER.encode() + b"\n\n", "error: password_file: the file holds more than one line"),
        (MARKER.encode() + b"\r\r", "error: password_file: the file holds more than one line"),
        (MARKER.encode() + b"\rx", "error: password_file: the file holds more than one line"),
        # Every line boundary Python knows, as the webhook body is split.
        (MARKER.encode() + b"\x0bx", "error: password_file: the file holds more than one line"),
        (MARKER.encode() + b"\x0cx", "error: password_file: the file holds more than one line"),
        ((MARKER + "\u2028x").encode(), "error: password_file: the file holds more than one line"),
        # UTF-16 without a byte order mark decodes as UTF-8, with a NUL after
        # each letter.
        (MARKER.encode("utf-16-le"), "error: password_file: the file holds a NUL character; save it as UTF-8"),
        # Read no further: a device or a large file is not read into memory.
        (MARKER.encode() * 205, "error: password_file: the file is longer than 1024 bytes"),
        (b"p" * 1024 + b"\n", "error: password_file: the file is longer than 1024 bytes"),
        # Windows PowerShell 5.1 writes `>` as UTF-16.
        (MARKER.encode("utf-16"), "error: password_file: the file is not UTF-8 text"),
        (MARKER.encode() + b"\xff", "error: password_file: the file is not UTF-8 text"),
        # Notepad's byte order mark would reach the login as part of the
        # password and fail it as a wrong one.
        (b"\xef\xbb\xbf" + MARKER.encode(),
         "error: password_file: the file starts with a byte order mark; save it without one"),
    ],
)
def test_a_file_that_holds_no_single_password_stops_before_any_output(startup, capsys, tmp_path, content, message):
    with pytest.raises(SystemExit) as exited:
        startup.run(_with_file(tmp_path, content))

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith(message)
    assert MARKER not in err
    assert startup.logins == []
    assert startup.served == []


@pytest.mark.parametrize("name", ["missing", "."])
def test_a_file_that_cannot_be_read_stops_before_any_output(startup, capsys, tmp_path, name):
    # A missing file and a directory: a mode the reader lacks is not tested,
    # since it stops no one on Windows and no one as root, as in the image.
    environ = {**_with_file(tmp_path, b"p"), "password_file": str(tmp_path / name)}

    with pytest.raises(SystemExit) as exited:
        startup.run(environ)

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    # The system's reason follows in brackets; its wording differs by system.
    assert ": error: password_file: the file cannot be read (" in err.splitlines()[-1]
    assert startup.logins == []


def test_a_password_file_beside_a_password_variable_stops_before_any_output(startup, capsys, tmp_path):
    # Neither wins: a password variable left in an env file would otherwise
    # decide, unseen, which password logs in.
    with pytest.raises(SystemExit) as exited:
        startup.run(_with_file(tmp_path, b"p", password=MARKER))

    out, err = capsys.readouterr()
    assert exited.value.code == 2
    assert out == ""
    assert err.splitlines()[-1].endswith(
        "error: set either password_file or the password environment variable, not both"
    )
    assert MARKER not in err
    assert startup.logins == []


@pytest.mark.parametrize("argv", [("--password_file", "x"), ("--password_file=x",)])
def test_password_file_is_not_an_option(startup, capsys, argv):
    # Like the password, it is read from the environment only: one place to
    # look for where the password comes from.
    with pytest.raises(SystemExit) as exited:
        startup.run(DEMO, *argv)

    assert exited.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1].endswith(
        "error: unrecognized arguments, not shown: one may be the password"
    )
    assert startup.logins == []
