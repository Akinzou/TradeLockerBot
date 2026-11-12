"""Exact console bytes, colour codes and reset lines included: the
characterization suite strips colours, so they are pinned here. And which
lines are handed on to the notification channel, as what text (ADR 0027)."""

import math

import pytest

from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.application.refusal import NoBalance, UnknownSymbol
from tradelocker_bot.domain.lot_sizing import UnusableQuantity
from tradelocker_bot.domain.signal import InvalidSignal, Side

GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"

# The texts the console hands on; no test above reads it, and each test
# below gives the console its own list.
NOTIFIED = []


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda c: c.locked(), "Normal: Locked\n"),
        (lambda c: c.closing("XAUUSD"), "Closing: XAUUSD\n"),
        (lambda c: c.order_placed(9001), f"{GREEN}Order placed successfully, order ID: 9001\n{RESET}\n"),
        (lambda c: c.unlocked(), "Normal: Unlocked\n"),
    ],
)
def test_prints_the_legacy_line(capsys, call, expected):
    call(PrintingConsole(NOTIFIED.append))

    assert capsys.readouterr().out == expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (InvalidSignal(2, "direction", "long", "buy or sell"),
         "line 2 (direction) is 'long', expected buy or sell"),
        (InvalidSignal(7, "inversion", None, "Invert or NonInvert"),
         "line 7 (inversion) is missing, expected Invert or NonInvert"),
        # Webhook text is printed escaped, so it cannot colour, rewrite or
        # forge the operator's log lines.
        (InvalidSignal(6, "action", "\x1b[92mopen\r", "open or close"),
         r"line 6 (action) is '\x1b[92mopen\r', expected open or close"),
        (InvalidSignal(4, "take profit", "9" * 100, "a whole number"),
         f"line 4 (take profit) is '{'9' * 40}'... (100 characters), expected a whole number"),
        # Refused once the broker answered (ADR 0009), in the same shape.
        (NoBalance(), "the account balance is missing or not a number, expected a number to size the position from"),
        (UnknownSymbol("GBPUSD"), "line 1 (symbol) is 'GBPUSD', expected an instrument the broker lists"),
        (UnknownSymbol("\x1b[2J" + "X" * 60),
         r"line 1 (symbol) is '\x1b[2J" + "X" * 36 + "'... (64 characters), expected an instrument the broker lists"),
        (UnusableQuantity(balance=10.0, quantity=0.0),
         "line 3 (lot) gives 0.0 at a balance of 10.0, expected a quantity above 0"),
        (UnusableQuantity(balance=1000, quantity=math.inf),
         "line 3 (lot) gives inf at a balance of 1000, expected a quantity above 0"),
        (UnusableQuantity(balance=-500.0, quantity=-0.05),
         "the account balance is -500.0, expected a positive number to size the position from"),
        (UnusableQuantity(balance=math.inf, quantity=math.inf),
         "the account balance is inf, expected a positive number to size the position from"),
    ],
)
def test_a_rejected_signal_names_the_line_and_shows_its_value_escaped(capsys, reason, expected):
    PrintingConsole(NOTIFIED.append).rejected(reason)

    assert capsys.readouterr().out == f"{RED}Signal rejected: {expected}\n{RESET}\n"


NO_POSITION = "no XAUUSD position is open"


@pytest.mark.parametrize(
    ("side", "reason", "expected"),
    [
        (Side.BUY, "Not enough margin", f"the broker refused to buy XAUUSD ('Not enough margin'); {NO_POSITION}"),
        (Side.SELL, None, f"the broker refused to sell XAUUSD (no reason given); {NO_POSITION}"),
        # The broker's text, escaped like webhook text: it cannot forge a line.
        (Side.BUY, "\x1b[92mfilled\r", r"the broker refused to buy XAUUSD ('\x1b[92mfilled\r'); " + NO_POSITION),
        # Cut later than a payload value: a reason is a sentence.
        (Side.BUY, "m" * 300, f"the broker refused to buy XAUUSD ('{'m' * 160}'... (300 characters)); {NO_POSITION}"),
    ],
)
def test_a_rejected_order_names_the_side_the_symbol_and_the_brokers_reason(capsys, side, reason, expected):
    PrintingConsole(NOTIFIED.append).order_rejected("XAUUSD", side, reason, 0)

    assert capsys.readouterr().out == f"{RED}Order rejected: {expected}\n{RESET}\n"


@pytest.mark.parametrize(
    ("open_positions", "state"),
    [
        (0, NO_POSITION),
        (1, "the broker lists 1 open XAUUSD position, check it in TradeLocker"),
        (3, "the broker lists 3 open XAUUSD positions, check them in TradeLocker"),
        (None, "the position count got no answer, check XAUUSD in TradeLocker"),
    ],
)
def test_a_rejected_order_ends_with_what_the_broker_lists_afterwards(capsys, open_positions, state):
    PrintingConsole(NOTIFIED.append).order_rejected("XAUUSD", Side.BUY, "Not enough margin", open_positions)

    out = capsys.readouterr().out
    assert out == f"{RED}Order rejected: the broker refused to buy XAUUSD ('Not enough margin'); {state}\n{RESET}\n"


@pytest.mark.parametrize(
    ("open_positions", "seconds", "state"),
    [
        (1, 60.0, "the broker lists 1 open XAUUSD position 60 seconds after the first close request; "
                  "later signals wait until it closes, check it in TradeLocker"),
        # Whole seconds: a real clock overshoots each pause by a little.
        (3, 61.73, "the broker lists 3 open XAUUSD positions 61 seconds after the first close request; "
                   "later signals wait until they close, check them in TradeLocker"),
    ],
)
def test_a_position_still_open_says_how_long_and_that_later_signals_wait(capsys, open_positions, seconds, state):
    PrintingConsole(NOTIFIED.append).still_closing("XAUUSD", open_positions, seconds)

    assert capsys.readouterr().out == f"{RED}Still closing: {state}\n{RESET}\n"


def test_a_broker_call_without_an_answer_names_the_symbol_and_the_exception_type_alone(capsys):
    class TLAPIException(Exception):
        pass

    # The exception's text stays out: the client's can hold a token or the
    # server's answer (ADR 0025), and this line leaves the host.
    PrintingConsole(NOTIFIED.append).broker_failed("XAUUSD", TLAPIException("Bearer eyJhbGciOi..."))

    assert capsys.readouterr().out == (
        f"{RED}Broker failed: a call for XAUUSD got no answer (TLAPIException); the signal stopped there, "
        f"check XAUUSD in TradeLocker\n{RESET}\n")


@pytest.mark.parametrize(
    ("call", "text"),
    [
        (lambda c: c.rejected(UnknownSymbol("GBPUSD")),
         "Signal rejected: line 1 (symbol) is 'GBPUSD', expected an instrument the broker lists"),
        (lambda c: c.order_rejected("XAUUSD", Side.BUY, None, 1),
         "Order rejected: the broker refused to buy XAUUSD (no reason given); "
         "the broker lists 1 open XAUUSD position, check it in TradeLocker"),
        (lambda c: c.still_closing("XAUUSD", 1, 60.0),
         "Still closing: the broker lists 1 open XAUUSD position 60 seconds after the first close request; "
         "later signals wait until it closes, check it in TradeLocker"),
        (lambda c: c.broker_failed("XAUUSD", ConnectionError("refused")),
         "Broker failed: a call for XAUUSD got no answer (ConnectionError); the signal stopped there, "
         "check XAUUSD in TradeLocker"),
        (lambda c: c.bot_failed("XAUUSD", KeyError("access_token: eyJ...")),
         "Bot failed: an error in the bot (KeyError) while handling XAUUSD; the signal stopped there, "
         "check XAUUSD in TradeLocker"),
    ],
)
def test_each_red_line_is_handed_on_as_its_text_without_colours(capsys, call, text):
    notified = []

    call(PrintingConsole(notified.append))

    assert notified == [text]
    assert capsys.readouterr().out == f"{RED}{text}\n{RESET}\n"


@pytest.mark.parametrize(
    "call",
    [lambda c: c.locked(), lambda c: c.closing("XAUUSD"), lambda c: c.order_placed(9001), lambda c: c.unlocked()],
)
def test_the_lines_of_a_signal_that_went_as_expected_are_not_handed_on(call):
    notified = []

    call(PrintingConsole(notified.append))

    assert notified == []


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (138.5, "Closed after 138 seconds from the first close request: the broker lists no open XAUUSD position"),
        (3600.0, "Closed after 3600 seconds from the first close request: the broker lists no open XAUUSD position"),
    ],
)
def test_a_close_that_ends_after_the_warning_prints_green_and_is_handed_on(capsys, seconds, text):
    # Handed on though nothing is left to do: the chat that was told later
    # signals wait has to learn that the wait is over. Green, since it asks
    # nothing of the operator.
    notified = []

    PrintingConsole(notified.append).closed("XAUUSD", seconds)

    assert notified == [text]
    assert capsys.readouterr().out == f"{GREEN}{text}\n{RESET}\n"
