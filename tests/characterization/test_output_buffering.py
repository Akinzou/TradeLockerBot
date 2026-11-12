"""Characterization tests for when the bot's lines reach the log (ADR 0026).

Without a terminal, as in the README's Compose example, Python opens stdout
block-buffered: a line waits until 8 KB pile up, something flushes, or the
process ends. The bot's lines waited for uvicorn's next access line, so a
trade's lines showed only with the next alert. The stdout here is Python's
own text layer over an in-memory file, opened as without a terminal, so what
reached the file is what ``docker logs`` would show.
"""

import io
import sys

import pytest

from tests.characterization.harness import DEMO, SERVE, Startup, broker, order_rejection, payload, serve
from tests.characterization.webhook_driver import finish, post


class Stdout(io.TextIOWrapper):
    """Block-buffered stdout that records, for each write, what had reached
    the file before it, so a test can ask what was written out when the
    server started, a moment the startup returns from only in tests."""

    def __init__(self):
        self.file = io.BytesIO()
        # Linux's line ends, as in the image, on every platform the tests run.
        super().__init__(self.file, encoding="utf-8", newline="\n")
        self.before = []

    def write(self, text):
        self.before.append((text, self.written()))
        return super().write(text)

    def written(self):
        return self.file.getvalue().decode()


def replace_stdout(monkeypatch):
    # Called in the test body, not a fixture: pytest puts its own capture back
    # on sys.stdout between a fixture's setup and the test.
    stdout = Stdout()
    monkeypatch.setattr(sys, "stdout", stdout)
    return stdout


def test_the_startup_lines_are_written_out_before_the_server_starts(monkeypatch):
    # The operator checks the account before the first alert trades on it.
    stdout = replace_stdout(monkeypatch)
    Startup(monkeypatch, broker()).run(DEMO)

    [at_start] = [written for text, written in stdout.before if text == SERVE]
    assert "|_   _| __ __ _" in at_start
    assert "Logged in: acc_id 76, acc_num 1\n" in at_start


@pytest.mark.parametrize(
    ("broker_options", "lines", "expected"),
    [
        pytest.param({}, payload(), ["Normal: Locked", "Order placed successfully, order ID: 9001",
                                     "Normal: Unlocked"], id="handled"),
        pytest.param({}, payload(direction="long"), ["Signal rejected: line 2 (direction)"], id="payload rejected"),
        pytest.param({"order_results": (order_rejection(),)}, payload(),
                     ["Order rejected: the broker refused to buy XAUUSD", "Normal: Unlocked"], id="order rejected"),
    ],
)
def test_a_signals_lines_are_written_out_without_waiting_for_the_next_request(
        monkeypatch, broker_options, lines, expected):
    # No request follows this one, so nothing else writes the buffer out.
    stdout = replace_stdout(monkeypatch)
    app = serve(monkeypatch, broker(**broker_options))

    _, threads = post(app, "/strategy", "\n".join(lines).encode())
    finish(threads)

    written = stdout.written()
    assert [line for line in expected if line not in written] == []
