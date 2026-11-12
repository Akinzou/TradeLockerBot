"""How a value from outside the bot appears in an operator line: the
webhook's, the broker's and Telegram's text alike."""

# Enough to recognise a mistyped field; a longer value is cut, so a hostile
# payload cannot flood the log with one line.
SHOWN_CHARACTERS = 40

# A reason is a sentence rather than a field, so it is cut later; still
# cut, since the text is the broker's or Telegram's, not the bot's.
SHOWN_REASON_CHARACTERS = 160


def shown(value: str, limit: int = SHOWN_CHARACTERS) -> str:
    # repr, not the raw text: the value comes from outside, and its control
    # characters (ESC, CR) could otherwise colour or forge operator lines.
    if len(value) <= limit:
        return repr(value)
    return f"{value[:limit]!r}... ({len(value)} characters)"
