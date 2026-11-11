"""The inbound HTTP adapter: the webhook the alert sender posts to (ADR 0010).

It turns a request body into lines and hands them to ``handle`` in a thread
of their own. It knows nothing of signals, the broker or the lock, so the
composition root decides what handles the lines.
"""

import threading
from typing import Callable

from fastapi import FastAPI, Request


def create_app(path: str, handle: Callable[[list[str]], None]) -> FastAPI:
    """The app that serves the webhook at ``path``, and nothing else.

    The request is still answered before ``handle`` finishes, a known defect
    that changes in a behaviour step of its own (roadmap step 6).
    """
    # No OpenAPI schema, and with it no /docs or /redoc, which need it: the
    # schema names every route, so serving it would publish the secret path
    # (ADR 0011). docs_url and redoc_url stay at their defaults because they
    # do nothing without the schema; setting them too would read as a second
    # line of defence that is not there.
    # No slash redirects either (ADR 0013): Starlette builds the redirect's
    # address from the request's scheme, which is http:// behind a TLS proxy
    # uvicorn does not trust, so a sender that follows it sends the secret
    # path and the signal again in plain text. A path that differs by a
    # slash answers 404 like any address the app does not serve.
    app = FastAPI(openapi_url=None, redirect_slashes=False)

    @app.post(path)
    async def process_webhook(request: Request):
        payload_bytes = await request.body()
        lines = payload_bytes.decode().splitlines()
        # A thread per request, started before the answer: the lock inside
        # `handle` queues signals, so the sender is never kept waiting on one.
        threading.Thread(target=handle, args=(lines,)).start()

    return app
