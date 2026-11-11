"""Where the generated webhook path comes from (ADR 0012).

The startup tests pin the path's shape. A shape says nothing about the
source, though: a path drawn from ``random`` can have exactly the same shape.
This test pins the source, so a generator that is not meant for secrets
cannot come back unnoticed.
"""

import secrets

from tradelocker_bot.adapters.webhook_path import random_webhook_path


def test_the_path_is_a_24_byte_url_safe_token_from_the_secrets_module(monkeypatch):
    # The recorder replaces the public `secrets.token_urlsafe`, not the
    # standard library's internals behind it, so the pin holds whichever way
    # a future Python implements it. `random`, a private `random.Random()`, a
    # hex token or a smaller token never call it with 24 and fail here.
    requested = []

    def token_urlsafe(nbytes=None):
        requested.append(nbytes)
        return "token"

    monkeypatch.setattr(secrets, "token_urlsafe", token_urlsafe)

    assert random_webhook_path() == "/token"
    assert requested == [24]
