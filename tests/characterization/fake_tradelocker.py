"""In-memory stand-in for ``tradelocker.TLAPI``.

Every call is bound against the real ``TLAPI`` method signature before the
fake answers, so a renamed or missing argument fails here exactly as it would
against the broker. A free-form ``**kwargs`` fake would let such mistakes pass
the whole suite and only surface in production.

Return values and failure modes follow ``TRADELOCKER_VERSION``: ``create_order``
returns an integer id and *raises* ``TLAPIOrderException`` on rejection, and
``close_all_positions`` only requests a close, which the broker may fill later.

Argument *types* are deliberately not checked. ``TLAPI`` methods are wrapped
in ``tl_typechecked``, which is typeguard's ``typechecked`` only when typeguard
is installed and a no-op otherwise. typeguard is not a tradelocker dependency
and is absent from the image, so production forwards any value (e.g.
``side="Buy"``) to the broker unchecked. Type-checking here would pin
rejections that production never performs.
"""

import inspect
from collections import Counter

import pandas as pd
from tradelocker import TLAPI

# The client version this fake mirrors; requirements.txt pins the same one
# (tests/test_broker_client_version.py).
TRADELOCKER_VERSION = "0.56.2"

# The real client builds the account state by zipping the broker's column
# names with its values, so a field can be absent rather than None.
NO_BALANCE_FIELD = object()

# The client calls the handler makes, each of which can be scheduled to fail.
BROKER_CALLS = frozenset({
    "get_account_state", "get_all_instruments", "get_all_positions",
    "close_all_positions", "create_order",
})


def _bind_to_real(method_name, *args, **kwargs):
    """Return every argument by parameter name, defaults filled in, as the real
    method sees them.

    Recording the full request rather than the call's spelling lets a caller
    switch between positional and keyword arguments, or pass a default
    explicitly, without changing what the pins compare: the broker receives
    the same request either way.
    """
    bound = inspect.signature(getattr(TLAPI, method_name)).bind(None, *args, **kwargs)
    bound.apply_defaults()
    arguments = dict(bound.arguments)
    del arguments["self"]
    return arguments


class FakeTradeLocker:
    def __init__(
        self,
        balance,
        instrument_ids,
        open_positions=(),
        order_results=(9001,),
        close_requests_to_fill=1,
        failures=None,
        account_id=76,
        acc_num=1,
    ):
        """``order_results`` items are order ids to return or exceptions to raise.

        ``close_requests_to_fill`` is how many close requests an instrument's
        positions need before the broker reports them gone.

        ``failures`` maps ``(method name, nth call)``, counted from 1, to an
        exception that call raises. The call is recorded, because the bot made
        it, but has no effect: a close that fails is not counted towards
        ``close_requests_to_fill``. A key the fake would never reach is
        refused, so a misspelt injection cannot pass as a tested failure.
        """
        # The account the real client chose at login, under its attribute names.
        self.account_id = account_id
        self.acc_num = acc_num
        self._balance = balance
        self._instrument_ids = dict(instrument_ids)
        self._open_positions = list(open_positions)
        self._order_results = list(order_results)
        self._close_requests_to_fill = close_requests_to_fill
        self._close_requests = {}
        self._failures = dict(failures or {})
        unreachable = [key for key in self._failures if key[0] not in BROKER_CALLS or key[1] < 1]
        if unreachable:
            raise ValueError(f"failures the fake never reaches: {unreachable}")
        self._call_counts = Counter()
        self.calls = []

    def _record(self, *call):
        self.calls.append(call)
        self._call_counts[call[0]] += 1
        failure = self._failures.get((call[0], self._call_counts[call[0]]))
        if failure is not None:
            raise failure

    def get_account_state(self):
        _bind_to_real("get_account_state")
        self._record("get_account_state")
        if self._balance is NO_BALANCE_FIELD:
            return {}
        return {"projectedBalance": self._balance}

    def get_all_instruments(self):
        # The two columns the bot reads, typed as the client types them; the
        # real frame has more.
        _bind_to_real("get_all_instruments")
        self._record("get_all_instruments")
        return pd.DataFrame({
            "tradableInstrumentId": pd.Series(list(self._instrument_ids.values()), dtype="int64"),
            "name": pd.Series(list(self._instrument_ids), dtype="object"),
        })

    def get_all_positions(self):
        _bind_to_real("get_all_positions")
        self._record("get_all_positions")
        return pd.DataFrame({"tradableInstrumentId": self._open_positions}, dtype="int64")

    def close_all_positions(self, *args, **kwargs):
        instrument_id = _bind_to_real("close_all_positions", *args, **kwargs)["instrument_id_filter"]
        self._record("close_all_positions", instrument_id)
        requests = self._close_requests.get(instrument_id, 0) + 1
        self._close_requests[instrument_id] = requests
        if requests >= self._close_requests_to_fill:
            self._open_positions = [p for p in self._open_positions if p != instrument_id]
        return True

    def create_order(self, *args, **kwargs):
        order = _bind_to_real("create_order", *args, **kwargs)
        self._record("create_order", order.pop("instrument_id"), order)
        result = self._order_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def open_positions(self):
        return list(self._open_positions)

    def orders(self):
        return [call for call in self.calls if call[0] == "create_order"]
