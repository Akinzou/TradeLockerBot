"""In-memory stand-in for ``tradelocker.TLAPI``.

Every call is bound against the real ``TLAPI`` method signature before the
fake answers, so a renamed or missing argument fails here exactly as it would
against the broker. A free-form ``**kwargs`` fake would let such mistakes pass
the whole suite and only surface in production.

Return values and failure modes follow tradelocker 0.56.2: ``create_order``
returns an integer id and *raises* ``TLAPIOrderException`` on rejection, and
``close_all_positions`` only requests a close, which the broker may fill later.
"""

import inspect

import pandas as pd
from tradelocker import TLAPI


def _bind_to_real(method_name, *args, **kwargs):
    inspect.signature(getattr(TLAPI, method_name)).bind(None, *args, **kwargs)


class FakeTradeLocker:
    def __init__(
        self,
        balance,
        instrument_ids,
        open_positions=(),
        order_results=(9001,),
        close_requests_to_fill=1,
    ):
        """``order_results`` items are order ids to return or exceptions to raise.

        ``close_requests_to_fill`` is how many close requests an instrument's
        positions need before the broker reports them gone.
        """
        self._balance = balance
        self._instrument_ids = dict(instrument_ids)
        self._open_positions = list(open_positions)
        self._order_results = list(order_results)
        self._close_requests_to_fill = close_requests_to_fill
        self._close_requests = {}
        self.calls = []

    def get_account_state(self):
        _bind_to_real("get_account_state")
        self.calls.append(("get_account_state",))
        return {"projectedBalance": self._balance}

    def get_instrument_id_from_symbol_name(self, *args, **kwargs):
        _bind_to_real("get_instrument_id_from_symbol_name", *args, **kwargs)
        symbol_name = args[0] if args else kwargs["symbol_name"]
        self.calls.append(("get_instrument_id_from_symbol_name", symbol_name))
        return self._instrument_ids[symbol_name]

    def get_all_positions(self):
        _bind_to_real("get_all_positions")
        self.calls.append(("get_all_positions",))
        return pd.DataFrame({"tradableInstrumentId": self._open_positions}, dtype="int64")

    def close_all_positions(self, *args, **kwargs):
        _bind_to_real("close_all_positions", *args, **kwargs)
        instrument_id = args[0] if args else kwargs.get("instrument_id_filter", 0)
        self.calls.append(("close_all_positions", instrument_id))
        requests = self._close_requests.get(instrument_id, 0) + 1
        self._close_requests[instrument_id] = requests
        if requests >= self._close_requests_to_fill:
            self._open_positions = [p for p in self._open_positions if p != instrument_id]
        return True

    def create_order(self, *args, **kwargs):
        _bind_to_real("create_order", *args, **kwargs)
        self.calls.append(("create_order", args[0], kwargs))
        result = self._order_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def open_positions(self):
        return list(self._open_positions)

    def orders(self):
        return [call for call in self.calls if call[0] == "create_order"]
