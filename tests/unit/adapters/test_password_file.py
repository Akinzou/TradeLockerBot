"""``read_password_file`` reads no further than it needs (ADR 0024)."""

from tradelocker_bot.adapters import password_file
from tradelocker_bot.adapters.password_file import MAX_BYTES, read_password_file
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
    monkeypatch.setattr(password_file, "open", lambda path, mode: endless, raising=False)

    result = read_password_file("/dev/zero")

    assert result == Err(f"password_file: the file is longer than {MAX_BYTES} bytes")
    assert endless.sizes == [MAX_BYTES + 1]
