"""``log_in`` on its own, for what the startup tests cannot reach.

argparse's ``choices`` stop any other ``--env`` before the login, so the
startup tests never pass one. ``log_in`` is a public adapter function,
though, and a caller other than the argument parser gets the legacy error,
not a bare ``KeyError``.
"""

import pytest

from tradelocker_bot.adapters import tradelocker_broker
from tradelocker_bot.adapters.tradelocker_broker import log_in


@pytest.fixture
def logins(monkeypatch):
    calls = []
    monkeypatch.setattr(tradelocker_broker, "TLAPI", lambda **credentials: calls.append(credentials))
    return calls


@pytest.mark.parametrize("environment", ["paper", "Demo", ""])
def test_an_unknown_environment_is_refused_before_the_login(logins, environment):
    with pytest.raises(ValueError, match=r"^Invalid environment specified\. Use 'demo' or 'live'\.$"):
        log_in(environment, "u", "p", "s", 0, 0)

    assert logins == []


def test_the_environment_is_checked_before_the_account_selectors(logins):
    # The legacy order: the server was chosen before the selectors were read.
    with pytest.raises(ValueError, match="Invalid environment"):
        log_in("paper", "u", "p", "s", 2, 77)

    assert logins == []
