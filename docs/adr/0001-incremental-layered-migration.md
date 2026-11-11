# ADR 0001: Incremental migration to a layered architecture

- Status: Accepted
- Date: 2026-11-11

## Context

The bot is a single script (`main_without_ssl.py`) that parses TradingView
webhook payloads, sizes positions, and talks to the TradeLocker API and FastAPI
directly. Trading rules, I/O, retries and process startup sit in the same
functions, so none of them can be tested or changed in isolation.

The published Docker image (`ghcr.io/akinzou/tradelocker_bot:latest`) is
rebuilt from every merge to `master`, and users run it against live accounts.
Each merged change is therefore a production release.

## Decision

Move to a domain / application / adapters layout (Clean Architecture with
ports at the process boundaries: broker API, HTTP inbound, clock) **one small
pull request at a time**, never as a rewrite.

1. **Pin behaviour first.** Characterization tests (`tests/characterization/`)
   lock in today's observable behaviour against an in-memory broker fake. The
   fake binds every call against the real `tradelocker.TLAPI` signatures and
   mirrors its failure modes (rejections raise, closes may fill late). The tests
   were checked against deliberate mutations of the code, and every one was
   caught.
2. **Restructure without changing behaviour.** While code moves into layers,
   the characterization tests must stay green with their assertions unchanged.
   Only their seam (`tests/characterization/harness.py`, the one module that imports the code under test) may move, and the
   pull request must call out that edit. "Behaviour-preserving" means, for
   every input: the same sequence of broker calls with the same arguments, and
   the same outcome, including the exact exception type when it raises. Only code that is identical under this rule
   for *all* inputs, malformed ones included, moves in a structure step.
3. **Change behaviour separately.** Each intentional behaviour change gets its
   own pull request, its own ADR, and an explicit update to the characterization
   test that pinned the old behaviour.

## Consequences

- The external contract stays frozen until an ADR changes it (see
  [migration roadmap](../migration-roadmap.md#frozen-contract)).
- Progress is slower than a rewrite, but every step ships green and can be
  reverted on its own.
- Known defects are not fixed opportunistically during restructuring. They are
  listed in the roadmap and fixed in dedicated steps.

## Alternatives considered

- **Big-bang rewrite.** Rejected: no tests exist to show the rewrite matches
  live behaviour, and a single mistake would reach every user through `latest`.
- **Fix defects first, then restructure.** Rejected: fixes in the current
  shape would be untestable and get rewritten in the next step anyway.
