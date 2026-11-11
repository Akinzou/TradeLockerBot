"""The web server's log settings, which must not write the webhook path
(ADR 0016).

A module of its own rather than part of the webhook adapter: the app does
not know which server runs it, and only the composition root, which starts
uvicorn, needs these settings.
"""

import copy
from typing import Any

from uvicorn.config import LOGGING_CONFIG

# The request line is the method, the path and the protocol, and the path is
# the secret. The client and the status stay, so `docker logs` still shows
# that an alert arrived and how it was answered.
ACCESS_LOG_FORMAT = '%(levelprefix)s %(client_addr)s - "<request line hidden>" %(status_code)s'


def server_log_config() -> dict[str, Any]:
    """uvicorn's own log settings, with an access line that leaves the request
    line out.

    Only the format changes, through a field uvicorn documents, rather than a
    filter that rewrites the log record: the record's arguments are uvicorn's
    internals, and a filter that misread them after an upgrade would let the
    path through. A copy, because uvicorn writes into the dictionary it is
    given and the default is its module-level one.
    """
    config = copy.deepcopy(LOGGING_CONFIG)
    config["formatters"]["access"]["fmt"] = ACCESS_LOG_FORMAT
    return config
