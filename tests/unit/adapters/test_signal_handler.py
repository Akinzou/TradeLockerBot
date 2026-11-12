"""``SignalHandler`` names every exception that ends a valid signal in one
red line before it leaves the thread (ADR 0027). The broker failures, with
the client's own exception, are pinned in the characterization suite."""

import threading

import pytest

from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.adapters.signal_handler import SignalHandler


PAYLOAD = ["XAUUSD", "buy", "0.01/100", "500", "1000", "open", "NonInvert"]


class FailingUseCase:
    def __init__(self, error):
        self.error = error

    def execute(self, signal):
        raise self.error


def test_an_exception_that_is_not_the_brokers_is_named_by_type_and_raised_as_it_was(capsys):
    error = TypeError("no operator line for NewRefusal(secret=...)")
    notified = []
    lock = threading.Lock()
    handler = SignalHandler(FailingUseCase(error), PrintingConsole(notified.append), lock)

    with pytest.raises(TypeError) as raised:
        handler.handle(PAYLOAD)

    assert raised.value is error
    assert notified == ["Bot failed: an error in the bot (TypeError) while handling XAUUSD; "
                        "the signal stopped there, check XAUUSD in TradeLocker"]
    assert "secret" not in capsys.readouterr().out
    assert not lock.locked()
