"""``read_secret_file`` reads no further than it needs (ADR 0024), and names
the setting whose file is wrong (ADR 0027)."""

from tradelocker_bot.adapters import secret_file
from tradelocker_bot.adapters.secret_file import MAX_BYTES, read_secret_file
from tradelocker_bot.domain.result import Err


class EndlessFile:
    """A file with no end, as ``/dev/zero`` is: a read to the end never returns."""

    def __init__(self):
        self.sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        self.sizes.append(size)
        assert size is not None and size >= 0, "a read to the end of an endless file never returns"
        return b"p" * size


def test_an_endless_file_is_refused_after_one_bounded_read(monkeypatch):
    endless = EndlessFile()
    monkeypatch.setattr(secret_file, "open", lambda path, mode: endless, raising=False)

    result = read_secret_file("/dev/zero", "password_file")

    assert result == Err(f"password_file: the file is longer than {MAX_BYTES} bytes")
    assert endless.sizes == [MAX_BYTES + 1]


def test_each_message_names_the_setting_whose_file_is_wrong(tmp_path):
    path = tmp_path / "token"
    path.write_bytes(b"")

    assert read_secret_file(path, "telegram_token_file") == Err("telegram_token_file: the file is empty")
    assert read_secret_file(tmp_path / "missing", "telegram_token_file") == Err(
        "telegram_token_file: the file cannot be read (No such file or directory)")
