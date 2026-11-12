"""The notifier's stop, as a real interpreter runs it at exit (ADR 0027).

The other startup pins replace ``atexit`` and run its functions by hand.
This one runs a separate Python, so what it pins is Python's own order:
the exit function runs only once every webhook thread has ended, however
``main`` ends, so a red line a signal prints late still reaches the chat.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PROGRAM = """
import io, json, sys, threading, time
from tradelocker_bot import composition_root
from tradelocker_bot.adapters.system_clock import SystemClock
from tradelocker_bot.adapters.telegram import TelegramSettings

class Answer(io.BytesIO):
    status = 200

def urlopen(request, timeout):
    print("sent:", json.loads(request.data)["text"], flush=True)
    return Answer(b'{"ok": true}')

composition_root.urlopen = urlopen
notifier = composition_root.start_notifier(TelegramSettings("1:a", "1"), SystemClock())

def signal_still_running():
    time.sleep(0.5)
    notifier.notify("Broker failed: a call for XAUUSD got no answer")

threading.Thread(target=signal_still_running).start()
notifier.end(composition_root.STOP_SECONDS)
ENDING
"""


@pytest.mark.parametrize(
    "ending",
    ["pass", "raise ConnectionError('login')", "raise KeyboardInterrupt", "sys.exit(1)"],
    ids=["return", "failed login", "Ctrl+C", "exit"],
)
def test_a_line_from_a_signal_still_running_when_main_ends_is_sent_before_the_process_ends(ending):
    run = subprocess.run([sys.executable, "-c", PROGRAM.replace("ENDING", ending)], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)

    assert "sent: Broker failed: a call for XAUUSD got no answer" in run.stdout, run.stderr
    assert "not sent" not in run.stdout
