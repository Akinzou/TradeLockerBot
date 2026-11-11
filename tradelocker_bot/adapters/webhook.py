"""The inbound HTTP adapter: the webhook the alert sender posts to (ADR 0010).

It turns a request body into lines and hands them to ``handle`` in a thread
of their own. It knows nothing of signals, the broker or the lock, so the
composition root decides what handles the lines.
"""

import threading
from typing import Callable

from fastapi import FastAPI, Request


def create_app(path: str, handle: Callable[[list[str]], None]) -> FastAPI:
    """The app that serves the webhook at ``path``.

    FastAPI's defaults are kept, the API docs included, and the request is
    answered before ``handle`` finishes: both are known defects that change
    in behaviour steps of their own (roadmap step 6), not in this move.
    """
    app = FastAPI()

    # The function's name is part of the served OpenAPI document (its
    # operation id and summary), so it keeps the legacy name.
    @app.post(path)
    async def process_webhook(request: Request):
        payload_bytes = await request.body()
        lines = payload_bytes.decode().splitlines()
        # A thread per request, started before the answer: the lock inside
        # `handle` queues signals, so the sender is never kept waiting on one.
        threading.Thread(target=handle, args=(lines,)).start()

    return app
