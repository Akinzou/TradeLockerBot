"""How ``ExecuteSignal`` waits for the broker to fill a close (ADR 0022):
counted again at once, then once a second, asked again every 10 seconds
of the clock, one line a minute in, and no upper limit."""

import pytest

from tests.unit.application.in_memory import (
    CLOSE_SIGNAL, LOOKUP, NO_ROWS, PAUSE, PLACE, START, XAUUSD, run, signal,
)


def test_open_requests_one_close_per_row_and_polls_until_none_are_left():
    # Counted again at once, since a close usually fills before that answer,
    # so the common case orders with no pause; then once a second, without
    # asking again until 10 seconds have passed (ADR 0022).
    assert run(signal(), rows=(2, 1, 0)) == [
        *START,
        NO_ROWS, ("request_close", XAUUSD), ("closing", "XAUUSD"), ("request_close", XAUUSD), ("closing", "XAUUSD"),
        NO_ROWS, PAUSE, NO_ROWS,
        PLACE, ("placed", 9001), ("unlocked",),
    ]


CLOSING = [("request_close", XAUUSD), ("closing", "XAUUSD")]
CLOSE_START = [LOOKUP, ("locked",), NO_ROWS]


def test_a_close_is_requested_again_only_once_10_seconds_have_passed():
    assert run(CLOSE_SIGNAL, rows=(1,) * 13 + (0,)) == [
        *CLOSE_START, *CLOSING, NO_ROWS,
        *[PAUSE, NO_ROWS] * 10,
        *CLOSING, NO_ROWS,
        PAUSE, NO_ROWS,
        ("unlocked",),
    ]


def test_the_10_seconds_are_the_clocks_not_a_count_of_polls():
    # Each count here takes 4 seconds, so the third poll is already 10
    # seconds after the request; counting polls would wait for the tenth.
    assert run(CLOSE_SIGNAL, rows=(1, 1, 1, 1, 0), seconds_per_count=4.0) == [
        *CLOSE_START, *CLOSING, NO_ROWS,
        PAUSE, NO_ROWS, PAUSE, NO_ROWS,
        *CLOSING, NO_ROWS,
        ("unlocked",),
    ]


@pytest.mark.parametrize("open_rows", [1, 2])
def test_a_position_still_open_a_minute_after_the_first_request_is_reported_once(open_rows):
    journal = run(CLOSE_SIGNAL, rows=(open_rows,) * 100 + (0,))

    # Once over the 90 seconds this close takes, at the first poll a minute
    # in, ahead of that poll's request again.
    warnings = [entry for entry in journal if entry[0] == "still closing"]
    assert warnings == [("still closing", "XAUUSD", open_rows, 60.0)]
    at = journal.index(warnings[0])
    assert journal[:at].count(PAUSE) == 60
    assert journal[at - 1:at + 2] == [NO_ROWS, warnings[0], ("request_close", XAUUSD)]
    assert journal.count(PAUSE) == 90


def test_the_warning_gives_the_time_since_the_first_request_not_the_threshold():
    # Each count takes 6 seconds here, so the first poll a minute in comes
    # 65 seconds after the request.
    journal = run(CLOSE_SIGNAL, rows=(1,) * 20 + (0,), seconds_per_count=6.0)

    assert [entry for entry in journal if entry[0] == "still closing"] == [("still closing", "XAUUSD", 1, 65.0)]


def test_the_10_seconds_run_from_when_the_requests_were_sent():
    # Each request takes 4 seconds here, as one the client has to retry can;
    # timed from before it, the next would go out after 6 seconds, and with
    # enough rows at once.
    assert run(CLOSE_SIGNAL, rows=(1,) * 23 + (0,), seconds_per_close=4.0) == [
        *CLOSE_START, *CLOSING, NO_ROWS,
        *[PAUSE, NO_ROWS] * 10,
        *CLOSING, NO_ROWS,
        *[PAUSE, NO_ROWS] * 10,
        *CLOSING, NO_ROWS,
        ("unlocked",),
    ]
