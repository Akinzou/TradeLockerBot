"""The ``closed`` line that ends a close which logged ``Still closing:``
(ADR 0028): once, at the count that finds no position,
and only after that warning."""

import pytest

from tests.unit.application.in_memory import (
    CLOSE_SIGNAL, NO_ROWS, PLACE, execute, run, signal,
)
from tradelocker_bot.application.ports import BrokerFailure
from tradelocker_bot.domain.result import Err


def _closed(journal):
    return [entry for entry in journal if entry[0] == "closed"]


@pytest.mark.parametrize(
    ("sig", "after"),
    [(CLOSE_SIGNAL, [("unlocked",)]), (signal(), [PLACE, ("placed", 9001), ("unlocked",)])],
    ids=["close", "open"],
)
def test_a_close_that_logged_still_closing_logs_one_closed_line_when_the_broker_lists_none(sig, after):
    # Each count takes half a second, so the clock at the count that finds
    # none differs from every earlier reading, the last request's included:
    # the seconds are read at that count.
    journal = run(sig, rows=(1,) * 101 + (0,), seconds_per_count=0.5)

    assert _closed(journal) == [("closed", "XAUUSD", 138.5)]
    at = journal.index(_closed(journal)[0])
    assert journal[at - 1] == NO_ROWS
    assert journal[at + 1:] == after


@pytest.mark.parametrize(
    "rows",
    [
        (1, 0),
        (1,) * 30 + (0,),
        # The last count that finds one is 59 seconds in, the one that finds
        # none 60: no `Still closing:` line, so no line that it ended.
        (1,) * 66 + (0,),
    ],
    ids=["at once", "in half a minute", "at the minute"],
)
def test_a_close_that_fills_before_the_warning_logs_no_closed_line(rows):
    # Every trade that replaces a position closes one; a line for each
    # would bury the one that matters.
    assert _closed(run(CLOSE_SIGNAL, rows=rows)) == []


@pytest.mark.parametrize(
    "failure",
    [("position_count", 80), ("request_close", 8)],
    ids=["a count", "a close request"],
)
def test_a_broker_failure_after_the_warning_logs_no_closed_line(failure):
    # The broker never listed none: `Broker failed:` says the signal stopped.
    result, journal = execute(CLOSE_SIGNAL, rows=(1,) * 100 + (0,), failures={failure: ConnectionError()})

    assert isinstance(result, Err) and isinstance(result.error, BrokerFailure)
    assert [entry for entry in journal if entry[0] == "still closing"] != []
    assert _closed(journal) == []
