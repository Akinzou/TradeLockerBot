"""The ``Clock`` port for tests, shared by the unit and characterization
suites so both agree on what counts as a close that never ends."""


class FakeClock:
    """Time that moves only when the code sleeps or a test advances it; each
    sleep is passed to ``record``. A loop that never ends fails on the time
    budget, and one that spins without sleeping on the reads, instead of
    hanging the suite."""

    BUDGET_SECONDS = 3600.0
    BUDGET_READS = 10_000

    def __init__(self, record):
        self._record = record
        self._now = 0.0
        self._reads = 0

    def now(self):
        self._reads += 1
        assert self._reads <= self.BUDGET_READS, "the close loop spins without sleeping"
        return self._now

    def advance(self, seconds):
        self._now += seconds
        assert self._now <= self.BUDGET_SECONDS, "the close loop never ended"

    def sleep(self, seconds):
        self._record(("sleep", seconds))
        self.advance(seconds)
