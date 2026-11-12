"""The password from the file ``password_file`` names (ADR 0024).

An adapter of its own rather than a port: only the composition root asks
for the password, at startup, so a port would have one implementation and
no caller inside the layers. The rules on the content are a function of the
bytes alone, kept apart from the read.
"""

import codecs

from tradelocker_bot.domain.result import Err, Ok, Result

# Far above any password a broker takes. Read no further, so a path that
# names a device or a large file is refused rather than read into memory.
MAX_BYTES = 1024


def read_password_file(path) -> Result[str, str]:
    """The password the file at ``path`` holds, or why it holds none."""
    try:
        with open(path, "rb") as file:
            content = file.read(MAX_BYTES + 1)
    except OSError as unread:
        return Err(f"password_file: the file cannot be read ({unread.strerror})")
    return password_from_bytes(content)


def password_from_bytes(content: bytes) -> Result[str, str]:
    r"""The one line ``content`` holds, less one trailing ``\r\n``, ``\n`` or
    ``\r``; nothing else is trimmed, as nothing is from the variable
    (ADR 0018).

    Decoded here rather than read as text, so every system sees the line
    endings as written. No message carries the content or the decoding
    error, which quotes it.
    """
    if len(content) > MAX_BYTES:
        return Err(f"password_file: the file is longer than {MAX_BYTES} bytes")
    # Refused rather than dropped: the last line ending is the only change
    # the bot makes to the file, so the password is what any editor shows.
    if content.startswith(codecs.BOM_UTF8):
        return Err("password_file: the file starts with a byte order mark; save it without one")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return Err("password_file: the file is not UTF-8 text")
    for ending in ("\r\n", "\n", "\r"):
        if text.endswith(ending):
            text = text[: -len(ending)]
            break
    # UTF-16 without a byte order mark decodes as UTF-8 with a NUL after
    # each letter, and would otherwise fail the login as a wrong password.
    if "\0" in text:
        return Err("password_file: the file holds a NUL character; save it as UTF-8")
    # Every line boundary Python knows, as the webhook body is split: a file
    # of several lines, an env file for one, would otherwise reach the
    # broker whole as one password.
    if not text:
        return Err("password_file: the file is empty")
    if text.splitlines() != [text]:
        return Err("password_file: the file holds more than one line")
    return Ok(text)
