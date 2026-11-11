"""The random webhook path ``--url generate`` serves (ADR 0012).

The path is the only thing protecting the endpoint, so it comes from
``secrets``, the standard library's source for secrets, and not from
``random``, whose generator is meant for simulations and shares its state with
any code in the process that seeds it. It is the same generator the README's
Quick start advises for a path chosen by hand, so both ways give the same kind
of path.
"""

import secrets

# 24 bytes give 192 bits and 32 URL-safe characters with no padding to escape.
PATH_BYTES = 24


def random_webhook_path():
    return "/" + secrets.token_urlsafe(PATH_BYTES)
