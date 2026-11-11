"""A signal that cannot be traded is refused before anything else happens
(ADR 0008): no broker call, no critical section, no exception, and one
operator line naming the line that stopped it.

Each row was a pinned defect before step 3: a crash in the webhook thread,
an order on the wrong side, a nonsensical quantity sent to the broker, an
action silently ignored, or a position closed and then left flat.
"""

import pytest
from tradelocker.exceptions import TLAPIException

from tests.characterization.harness import (
    XAUUSD_ID,
    RecordingLock,
    broker,
    console_lines,
    handle,
    payload,
)

LOT = "expected <lot>/<balance step>, two positive numbers"
NUMBER = "expected a whole number"


def rejected(text):
    return f"Signal rejected: {text}"


@pytest.mark.parametrize(
    ("scenario", "lines", "line"),
    [
        ("empty payload", [], "line 1 (symbol) is missing, expected an instrument name"),
        *[
            (f"payload cut to {length} lines", payload()[:length],
             "line 6 (action) is missing, expected open or close")
            for length in range(1, 6)
        ],
        ("open without line 7", payload()[:6], "line 7 (inversion) is missing, expected Invert or NonInvert"),
        ("unknown action", payload(action="hold"), "line 6 (action) is 'hold', expected open or close"),
        ("unknown direction", payload(direction="long"), "line 2 (direction) is 'long', expected buy or sell"),
        ("lot without a step", payload(lot="0.01"), f"line 3 (lot) is '0.01', {LOT}"),
        ("non-numeric lot", payload(lot="abc/100"), f"line 3 (lot) is 'abc/100', {LOT}"),
        ("lot with two steps", payload(lot="0.01/100/2"), f"line 3 (lot) is '0.01/100/2', {LOT}"),
        ("zero balance step", payload(lot="0.01/0"), f"line 3 (lot) is '0.01/0', {LOT}"),
        ("zero lot", payload(lot="0/100"), f"line 3 (lot) is '0/100', {LOT}"),
        ("negative lot", payload(lot="-0.01/100"), f"line 3 (lot) is '-0.01/100', {LOT}"),
        ("infinite lot", payload(lot="inf/100"), f"line 3 (lot) is 'inf/100', {LOT}"),
        ("NaN lot", payload(lot="nan/100"), f"line 3 (lot) is 'nan/100', {LOT}"),
        ("non-numeric take profit", payload(tp="5x"), f"line 4 (take profit) is '5x', {NUMBER}"),
        ("non-numeric stop loss", payload(sl="1e3"), f"line 5 (stop loss) is '1e3', {NUMBER}"),
        ("invalid inversion", payload(invert="Sideways"),
         "line 7 (inversion) is 'Sideways', expected Invert or NonInvert"),
        ("inversion in another case", payload(invert="invert"),
         "line 7 (inversion) is 'invert', expected Invert or NonInvert"),
    ],
)
def test_a_rejected_signal_touches_neither_the_broker_nor_the_lock(capsys, scenario, lines, line):
    fake = broker(open_positions=[XAUUSD_ID])
    lock = RecordingLock(fake)

    handle(fake, lines, lock)

    assert fake.calls == [], scenario
    assert lock.events == [], scenario
    assert fake.open_positions == [XAUUSD_ID], scenario
    assert console_lines(capsys) == [rejected(line)], scenario


def test_a_rejection_comes_before_a_broker_that_would_fail():
    # Before step 3, the failing balance read was the first thing to happen.
    fake = broker(failures={("get_account_state", 1): TLAPIException("down")})

    handle(fake, payload(lot="abc/100"))

    assert fake.calls == []
