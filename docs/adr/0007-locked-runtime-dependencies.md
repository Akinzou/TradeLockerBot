# ADR 0007: Install the image from a hashed lock of every runtime dependency

- Status: Accepted
- Date: 2026-11-11

## Context

`requirements.txt` pins only `tradelocker` (roadmap step 2b). `fastapi`,
`uvicorn` and every transitive package (pandas, numpy, requests, pydantic and
others) were resolved afresh on every image build. A rebuild with no commit
could therefore ship different code. A compromised or broken upstream release
would reach users as soon as the next publish ran. CI tested whatever versions
were current on the runner, which need not match what the image got
minutes later.

## Decision

1. `requirements.txt` stays the hand-edited list of what the bot needs.
   `requirements-lock.txt` is generated from it with `uv pip compile` and
   is never edited by hand. It pins every package to one version with all of
   that version's `sha256` hashes. The generating command is in the file's
   header.
2. The lock is resolved for the image: Python 3.11 on
   `x86_64-manylinux_2_28`. Resolving on a developer's machine would pick
   that machine's markers (`colorama` on Windows) and its Python's newest
   versions. numpy 2.5 already dropped 3.11, so a 3.12 resolution would not
   install in the image.
3. The Dockerfile installs `pip install --require-hashes -r
   requirements-lock.txt`. Under `--require-hashes` pip refuses any package
   that is not in the lock or does not match a hash.
4. CI checks both directions:
   - `tests/test_dependency_lock.py` checks the lock. Every package carries
     hashes, every requirement in `requirements.txt` is satisfied by its pin,
     and `tradelocker` is the version the broker fake mirrors.
   - The `docker-build` job compares `pip freeze` inside the image with the
     lock, excluding `pip` and `setuptools`. The sets must be equal.
   - The `tests` job installs the lock first, on Python 3.11 and 3.12, so the
     suite runs against the image's versions.

## Consequences

- An image rebuild installs exactly what CI tested. Moving a dependency is a
  reviewed change to the lock.
- Security fixes in dependencies no longer arrive by themselves. Regenerate
  the lock (add `--upgrade` or `--upgrade-package <name>`) and merge it like
  any other change.
- Local development may still install `requirements-dev.txt` on any
  platform. Its versions can differ from the lock, which CI covers.
- The base image `python:3.11-slim` is still a moving tag. Pinning it by
  digest is a separate step.

## Alternatives considered

- **`pip freeze` from a built image as the lock.** Rejected: the result has
  no hashes, and it records whatever happened to resolve, not a reviewed
  resolution.
- **pip-tools (`pip-compile`).** Rejected: it resolves only for the
  interpreter and platform it runs on. Producing the image's lock would need
  Docker on every developer's machine.
- **Poetry or a `pyproject.toml` lock.** Rejected for now: it changes how the
  project is installed everywhere, which is more than this step needs.
