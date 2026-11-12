"""The operator's Telegram chat: its settings and one message sent to it
(ADR 0027).

The adapter of the ``Chat`` port, which the notifier declares: only
adapters hand it text, the console's red lines and the startup's account
line, and the use case knows nothing of it. The bot token is part of every request's path, so nothing here returns
or prints a request, a URL or an exception's text: a failure is the HTTP
status with Telegram's own description, or the exception's type.
"""

import json
import re
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request

from tradelocker_bot.adapters.notifier import SendFailure
from tradelocker_bot.adapters.secret_file import read_secret_file
from tradelocker_bot.adapters.shown import SHOWN_REASON_CHARACTERS, shown
from tradelocker_bot.domain.result import Err, Ok, Result

API = "https://api.telegram.org"

# Long enough for a slow network, short enough that a message behind a hung
# connection is not held for minutes.
TIMEOUT_SECONDS = 10.0

# Telegram's limit for one message. The lines are cut far below it; the cut
# here keeps a longer one from being refused whole.
MAX_TEXT_CHARACTERS = 4096

# An answer is a small JSON object. Read no further, so a proxy's page or a
# hostile endless answer is not read into memory.
MAX_ANSWER_BYTES = 64 * 1024

# BotFather's form, digits, a colon, then the secret. Checked rather than
# trusted because the token becomes part of the request's path: a slash, a
# `?` or a `%` there would send the request, token included, to another path.
TOKEN = re.compile(r"[0-9]+:[A-Za-z0-9_-]+")

# A chat's number, negative for groups and channels, or a public channel's
# name, which Telegram makes 5 to 32 letters, digits and underscores.
CHAT_ID = re.compile(r"-?[0-9]+|@[A-Za-z][A-Za-z0-9_]{4,31}")


@dataclass(frozen=True)
class TelegramSettings:
    token: str = field(repr=False)
    chat_id: str


def telegram_from(env) -> Result[TelegramSettings | None, str]:
    """The settings from ``telegram_token_file`` and ``telegram_chat_id``,
    ``Ok(None)`` when neither is set, an empty one counting as not set.

    One without the other stops the bot rather than leaving Telegram off: the
    operator who set one expects the messages, and would learn otherwise only
    when one never came.
    """
    path, chat_id = env.get("telegram_token_file", ""), env.get("telegram_chat_id", "")
    if not path and not chat_id:
        return Ok(None)
    if not path:
        return Err("telegram_chat_id is set without telegram_token_file: set both, or neither")
    if not chat_id:
        return Err("telegram_token_file is set without telegram_chat_id: set both, or neither")
    token = read_secret_file(path, "telegram_token_file")
    if isinstance(token, Err):
        return token
    if not TOKEN.fullmatch(token.value):
        return Err("telegram_token_file: the file holds no bot token, "
                   "which is digits, a colon, then letters, digits, - and _")
    if not CHAT_ID.fullmatch(chat_id):
        return Err("telegram_chat_id: expected a chat's number, such as -1001234567890, or @ and a channel's name")
    return Ok(TelegramSettings(token.value, chat_id))


class TelegramChat:
    """The ``Chat`` port over Telegram: one message, as plain text."""

    def __init__(self, settings: TelegramSettings, urlopen, api: str = API, timeout: float = TIMEOUT_SECONDS):
        # `urlopen` has no default, so no test reaches Telegram by leaving it
        # out; the composition root passes urllib's.
        self._url = f"{api}/bot{settings.token}/sendMessage"
        chat_id = settings.chat_id
        self._chat_id = chat_id if chat_id.startswith("@") else int(chat_id)
        self._urlopen = urlopen
        self._timeout = timeout

    def send(self, text: str) -> Result[None, SendFailure]:
        # No parse_mode: the lines quote the webhook's and the broker's text,
        # which Markdown or HTML would read as markup, or refuse to send.
        body = json.dumps({
            "chat_id": self._chat_id,
            "text": text[:MAX_TEXT_CHARACTERS],
            "link_preview_options": {"is_disabled": True},
        }).encode()
        request = Request(self._url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                status, answer = response.status, response.read(MAX_ANSWER_BYTES)
        except HTTPError as error:
            # An answer still: Telegram's errors come as 4xx and 5xx.
            with error:
                status, answer = error.code, _read(error)
        # Every other failure, whatever its type, rather than the ones urllib
        # documents: an uncaught one would print its traceback, and the text
        # of some, such as an invalid URL's, holds the token.
        except Exception as error:
            cause = error.reason if isinstance(error, URLError) and isinstance(error.reason, Exception) else error
            return Err(SendFailure(f"no answer ({type(cause).__name__})", retry=True))
        return _outcome(status, answer)


def _read(error: HTTPError) -> bytes:
    try:
        return error.read(MAX_ANSWER_BYTES)
    except Exception:  # the status alone still says what failed
        return b""


def _outcome(status: int, answer: bytes) -> Result[None, SendFailure]:
    # Tried again on a flood answer, a server error and an answer that is not
    # Telegram's, which a proxy or a dropped connection gives; never on
    # another 4xx, which the same request would get again.
    retry = status == 429 or status >= 500 or 200 <= status < 300
    try:
        parsed = json.loads(answer)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        reason = f"HTTP {status}" if status >= 300 else f"HTTP {status}, an answer that is not Telegram's"
        return Err(SendFailure(reason, retry=retry))
    if parsed.get("ok") is True and 200 <= status < 300:
        return Ok(None)
    description = parsed.get("description")
    reason = f"HTTP {status}"
    if isinstance(description, str):
        reason += f", {shown(description, SHOWN_REASON_CHARACTERS)}"
    parameters = parsed.get("parameters")
    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
    # A number, as Telegram gave it; which waits to keep is the notifier's
    # to decide, in one place.
    if isinstance(retry_after, bool) or not isinstance(retry_after, int | float):
        retry_after = None
    return Err(SendFailure(reason, retry=retry, retry_after=_seconds(retry_after)))


def _seconds(value: int | float | None) -> float | None:
    # JSON reads any integer, and one beyond a float's range cannot be one.
    try:
        return None if value is None else float(value)
    except OverflowError:
        return None
