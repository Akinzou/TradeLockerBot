"""Characterization tests for the line that names the account after the login.

The client names the account it chose only at ``debug``, the level that also
writes the password and the tokens to the log, so the bot runs it at
``info`` and names the account itself (ADR 0025). The operator checks the
line before the first alert trades on that account. A failed login prints
no such line; ``test_startup.py`` pins its output.
"""

import pytest

from tests.characterization.harness import DEMO, LOGIN, SERVE, Startup, broker, console_lines


@pytest.mark.parametrize(
    ("selector", "account"),
    [
        ({}, {"account_id": 76, "acc_num": 1}),
        ({"acc_num": "2"}, {"account_id": 77, "acc_num": 2}),
        ({"acc_id": "77"}, {"account_id": 77, "acc_num": 2}),
    ],
)
def test_the_line_names_the_account_the_client_chose(monkeypatch, capsys, selector, account):
    Startup(monkeypatch, broker(**account)).run({**DEMO, **selector})

    assert console_lines(capsys)[-3:] == [
        LOGIN, f"Logged in: acc_id {account['account_id']}, acc_num {account['acc_num']}", SERVE,
    ]
