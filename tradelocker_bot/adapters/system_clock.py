import time


class SystemClock:
    """The ``Clock`` port over the interpreter's monotonic clock (ADR 0022).

    Monotonic rather than the wall clock: the wall clock can step back or
    forward, after an NTP correction or a manual change, and the close loop
    would then ask the broker again at once, or not for an hour.
    """

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
