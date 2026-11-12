"""A coloured line and its reset leave in one ``print`` (ADR 0026): the
notifier's thread and the webhook's threads print too, and a line printed
between the two would inherit the colour. The bytes alone cannot show it."""

import pytest

from tradelocker_bot.adapters import ascii_alerts


@pytest.mark.parametrize(
    ("write", "colour"),
    [(ascii_alerts.print_red, ascii_alerts.RED), (ascii_alerts.print_green, ascii_alerts.GREEN)],
    ids=["red", "green"],
)
def test_a_coloured_line_and_its_reset_are_one_print(monkeypatch, write, colour):
    printed = []
    monkeypatch.setattr(ascii_alerts, "print", lambda *args: printed.append(args), raising=False)

    write("Closed after 70 seconds")

    assert printed == [(f"{colour}Closed after 70 seconds\n{ascii_alerts.RESET}",)]
