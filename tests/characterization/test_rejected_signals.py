"""A signal that cannot be traded is refused with one operator line and no
exception. A payload error is refused before anything else happens (ADR
0008): no broker call and no critical section. What needs the broker's answer
is refused once the broker has answered, before any close request or order
(ADR 0009).

Each row was a pinned defect before step 3: a crash in the webhook thread,
an order on the wrong side, a nonsensical quantity sent to the broker, an
action silently ignored, or a position closed and then left flat.
"""

import pytest
from tradelocker.exceptions import TLAPIException

from tests.characterization.fake_tradelocker import NO_BALANCE_FIELD
from tests.characterization.harness import (
    BALANCE,
    LOCK_ACQUIRED,
    LOCK_RELEASED,
    LOOKUP,
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


NO_BALANCE = "the account balance is missing or not a number, expected a number to size the position from"
NOT_LISTED = "expected an instrument the broker lists"
NO_QUANTITY = "expected a quantity above 0"
BALANCE_IS = "the account balance is"
POSITIVE = "expected a positive number to size the position from"


@pytest.mark.parametrize(
    ("scenario", "fake_args", "lines", "calls", "line"),
    [
        # Each row raised or traded before step 3b: a TypeError from the lot
        # sizing, the client's ValueError, or an order for 0 or inf lots.
        ("no balance field", {"balance": NO_BALANCE_FIELD}, payload(), [BALANCE], NO_BALANCE),
        ("balance reported as null", {"balance": None}, payload(), [BALANCE], NO_BALANCE),
        ("balance reported as text", {"balance": "1000"}, payload(), [BALANCE], NO_BALANCE),
        ("quantity rounds to zero", {"balance": 10.0}, payload(), [BALANCE],
         f"line 3 (lot) gives 0.0 at a balance of 10.0, {NO_QUANTITY}"),
        ("negative balance", {"balance": -500.0}, payload(), [BALANCE], f"{BALANCE_IS} -500.0, {POSITIVE}"),
        ("zero balance", {"balance": 0}, payload(), [BALANCE], f"{BALANCE_IS} 0, {POSITIVE}"),
        ("quantity overflows", {"balance": 1000.0}, payload(lot="1e306/1"), [BALANCE],
         f"line 3 (lot) gives inf at a balance of 1000.0, {NO_QUANTITY}"),
        ("unknown symbol on open", {}, payload(symbol="GBPUSD"), [BALANCE, LOOKUP],
         f"line 1 (symbol) is 'GBPUSD', {NOT_LISTED}"),
        ("unknown symbol on close", {}, payload(symbol="GBPUSD", action="close"), [LOOKUP],
         f"line 1 (symbol) is 'GBPUSD', {NOT_LISTED}"),
        ("symbol in another case", {}, payload(symbol="xauusd"), [BALANCE, LOOKUP],
         f"line 1 (symbol) is 'xauusd', {NOT_LISTED}"),
    ],
)
def test_a_signal_the_broker_answer_rules_out_closes_nothing(capsys, scenario, fake_args, lines, calls, line):
    fake = broker(open_positions=[XAUUSD_ID], **fake_args)
    lock = RecordingLock(fake)

    handle(fake, lines, lock)

    assert fake.calls == calls, scenario
    assert lock.events == [("acquire", 0), ("release", len(calls))], scenario
    assert fake.open_positions == [XAUUSD_ID], scenario
    assert console_lines(capsys) == [LOCK_ACQUIRED, rejected(line), LOCK_RELEASED], scenario


def test_an_unknown_symbol_on_open_is_found_after_the_quantity_check():
    # The balance is read first, as before; a signal both unknown and unsized
    # names the quantity, the first thing that stopped it.
    fake = broker(balance=10.0)

    handle(fake, payload(symbol="GBPUSD"))

    assert fake.calls == [BALANCE]
