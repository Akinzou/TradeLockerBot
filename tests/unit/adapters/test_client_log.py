"""The real client's log, through ``log_in``, holds none of the login's
secrets (ADR 0025).

The client logs every request it sends, headers and body, at its default
level, ``debug``: the password in the login, the refresh token in a refresh
and the access token in every ``Authorization`` header. The container's log
kept them all. Here the real ``TLAPI`` talks to an in-memory server through a
stubbed ``requests``, so the log is the one the client would write.
"""

import base64
import json
import logging
import time

import pytest
import requests
from tradelocker import TLAPI, utils

from tradelocker_bot.adapters.tradelocker_broker import log_in

PASSWORD = "zq7pw"


def token(name, lifetime):
    """An unsigned JWT: the client reads its expiry and never checks it."""
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return ".".join([part({"alg": "HS256", "typ": "JWT"}),
                     part({"sub": name, "exp": int(time.time()) + lifetime}), "c2ln"])


# The first access token expires within the client's 30 minutes, so its
# first authorized request refreshes it: one login sends all three secrets.
LOGIN_TOKENS = {"accessToken": token("zq7access1", 600), "refreshToken": token("zq7refresh1", 86400)}
REFRESHED = {"accessToken": token("zq7access2", 3600), "refreshToken": token("zq7refresh2", 86400)}
SECRETS = [PASSWORD, *LOGIN_TOKENS.values(), *REFRESHED.values()]
ACCOUNTS = {"accounts": [
    {"id": 76, "name": "first", "currency": "USD", "accNum": 1, "accountBalance": "10"},
    {"id": 77, "name": "second", "currency": "USD", "accNum": 2, "accountBalance": "20"},
]}


class Server:
    """Answers the three routes a login reaches, and records the paths."""

    ANSWERS = {"/auth/jwt/token": LOGIN_TOKENS, "/auth/jwt/refresh": REFRESHED, "/auth/jwt/all-accounts": ACCOUNTS}

    def __init__(self):
        self.paths = []

    def request(self, url, **_):
        path = url.removeprefix("https://demo.tradelocker.com/backend-api")
        self.paths.append(path)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = json.dumps(self.ANSWERS[path]).encode()
        return response


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.NOTSET)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture
def server(monkeypatch):
    server = Server()
    for method in ("get", "post"):
        monkeypatch.setattr(requests, method, server.request)
    # The client waits a second before each try of a request.
    monkeypatch.setattr(utils.time, "sleep", lambda seconds: None)
    # One client per set of arguments, kept for the process: a fresh login each test.
    monkeypatch.setattr(TLAPI, "_instances", {})
    return server


@pytest.fixture
def log(monkeypatch):
    # The client's own logger, not caplog: caplog would set the level that is
    # under test. The level the client sets stays for the process, so it is
    # put back.
    logger = logging.getLogger("tradelocker.tradelocker_api")
    monkeypatch.setattr(logger, "level", logger.level)
    records = Records()
    logger.addHandler(records)
    yield records.lines
    logger.removeHandler(records)


@pytest.mark.parametrize(("acc_num", "acc_id"), [(0, 0), (2, 0), (0, 77)])
def test_a_login_writes_no_password_or_token_to_the_log(server, log, acc_num, acc_id):
    client = log_in("demo", "u", PASSWORD, "s", acc_num, acc_id)

    # It sent all three secrets, so a clean log is not an idle client's.
    assert server.paths == ["/auth/jwt/token", "/auth/jwt/refresh", "/auth/jwt/all-accounts"]
    assert client._access_token == REFRESHED["accessToken"]
    assert [secret for secret in SECRETS if any(secret in line for line in log)] == []


def test_the_client_still_logs_its_progress(server, log):
    # The level drops the request dumps, not the client's own account of what
    # it did: the operator's log still shows the login.
    log_in("demo", "u", PASSWORD, "s", 0, 0)

    assert log == [
        "Successfully fetched authentication tokens",
        "Successfully refreshed authentication tokens",
    ]
