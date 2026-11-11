# ADR 0009: Refuse what the broker rules out before closing anything

- Status: Accepted
- Date: 2026-11-11

## Context

Step 3 ([ADR 0008](0008-validate-the-signal-before-any-broker-call.md))
refuses every payload error before any broker call. Three problems were left,
because they can only be seen once the broker has answered. The roadmap
pinned them as defects:

- **Account state without a balance.** When the field was absent or null, lot
  sizing raised a `TypeError` in the webhook thread.
- **Unknown symbol.** The client raised a bare `ValueError` after the balance
  read, and the thread died with it.
- **Unusable quantity.** A lot can be valid on its own and still give a
  quantity no broker can trade at the current balance. It rounds to `0.0`
  when the balance is too small and overflows to `inf` with `1e306/1`. Both
  were sent to the broker as an order.

Before this step, the instrument lookup happened after the "Normal: Locked"
line. The legacy code also looked the instrument up a second time before
ordering, with nothing between the two lookups that could change the answer.

## Decision

1. **Refuse before the first close request.** `open` reads the balance,
   sizes the position and looks up the instrument, in that order. It writes
   "Normal: Locked" and touches positions only after all three succeed.
   `close` looks up the instrument first. A refused signal closes nothing,
   orders nothing and prints one operator line.

   ```mermaid
   flowchart TD
       S([valid signal]) --> A{action}
       A -- open --> B[read balance]
       B -- no number --> R1[/NoBalance/]
       B --> Q[quantity_for balance]
       Q -- "not finite, or not above 0" --> R2[/UnusableQuantity/]
       Q --> L1[look up instrument]
       A -- close --> L2[look up instrument]
       L1 -- not listed --> R3[/UnknownSymbol/]
       L2 -- not listed --> R3
       L1 --> LK1["Normal: Locked"] --> C1[close positions] --> O[place order]
       L2 --> LK2["Normal: Locked"] --> C2[close positions]
       R1 & R2 & R3 --> REJ["Signal rejected: ... (one line, no exception)"]
   ```

   A broker call that fails at any of these steps is still a `BrokerFailure`.
   It is returned at once and re-raised by the legacy handler (ADR 0006).

2. **A refusal is its own error type.** `NoBalance`, `UnknownSymbol` and
   `UnusableQuantity` form `Refusal`, and `ExecuteSignal.execute` now returns
   `Result[None, BrokerFailure | Refusal]`.
   - A refusal is not an `InvalidSignal`. The same payload trades on another
     account or at another balance, and a missing balance is not a payload
     line at all.
   - A refusal is not a `BrokerFailure` either. The broker answered, so there
     is nothing to retry or re-raise.
   - `NoBalance` and `UnknownSymbol` live in the application layer.
     `UnusableQuantity` lives in the domain, next to the rule that produces
     it.
   - The legacy handler branches on the error kind. It re-raises a broker
     failure as before and prints a refusal with the same
     `Signal rejected:` line as a payload error, without an exception.

3. **The unknown symbol comes from the instrument list, not from an
   exception.** The client's `get_instrument_id_from_symbol_name` raises a
   bare `ValueError` for a name it does not list. It raises the same bare
   `ValueError` when the broker's answer is empty or is not JSON (its
   `_get_response_json` turns the decode error into one). Telling the two
   apart would mean matching the exception's message, and that match breaks
   silently on a client upgrade. Getting it wrong would hide an outage behind
   a calm "unknown symbol" line.

   So the adapter reads `get_all_instruments()` and repeats the client's own
   match: exact name, and the first row when several match. The port returns
   `Ok(None)` for a name the broker does not list, and `Err` only when the
   broker did not answer. Two tests hold this in place:
   - One runs the client's own lookup against the same instrument list as
     the adapter, so a client upgrade that matches names differently fails
     in CI.
   - The other injects the client's empty-answer, bad-JSON and exact
     unknown-symbol `ValueError`s as lookup failures and checks that both are
     re-raised as broker failures.

4. **A balance must be a number.** An absent field, `null`, text such as
   `"1000"` and `true` all count as no balance. Coercing text would mean
   guessing what the broker meant. The operator line says "missing or not a
   number", because both reach the use case as `None`.

5. **One quantity rule.** The rounded quantity must be finite and above
   zero. This covers a balance too small, zero or negative, an overflowing
   lot and a NaN balance. The check runs after rounding, because the rounded
   number is what the broker would receive. The broker's own minimum lot and
   lot step are not checked here. The broker still rejects those orders, and
   that rejection is the "rejected order leaves the account flat" defect,
   which step 6 fixes.

6. **One instrument lookup.** The id found by the check is used to close and
   to order. Keeping the legacy second lookup would have made three calls
   where one answers the question. The roadmap had listed this for step 6;
   it moves here because the check made it free.

7. **The operator line keeps step 3's shape** of "what is found, expected
   what fits". The symbol is escaped and cut after 40 characters, like any
   webhook value (ADR 0008):

   ```text
   Signal rejected: the account balance is missing or not a number, expected a number to size the position from
   Signal rejected: line 3 (lot) gives 0.0 at a balance of 10.0, expected a quantity above 0
   Signal rejected: the account balance is -500.0, expected a positive number to size the position from
   Signal rejected: line 1 (symbol) is 'GBPUSD', expected an instrument the broker lists
   ```

   An unusable quantity names line 3 only when the balance is above zero.
   With a zero, negative or infinite balance, no lot would help, so the line
   names the balance instead.

## Consequences

- No signal, valid or not, and no well-formed broker answer raises from the
  use case any more. A broker that does not answer comes back as
  `Err(BrokerFailure)`, which only the legacy handler re-raises. An answer
  the adapter cannot read, such as an account state that is not a mapping,
  still raises on purpose, so a fault cannot pose as an outage (ADR 0006).
  ADR 0006's condition for step 5 is met.
- Pins changed, each listed in the pull request:
  - Every `open` call sequence loses the second lookup.
  - The lookup is recorded as `get_all_instruments`.
  - A lookup failure no longer prints "Normal: Locked".
  - The missing-balance, unknown-symbol and unusable-quantity rows move from
    the raising and trading pins to `test_rejected_signals.py`.
- A refusal is decided inside the lock, because it needs the broker's
  answer. The lock covers the same calls as before.
- The client's warning when two instruments share a name is gone. The first
  row is still used, as before.
- The instrument list is fetched once per process, as before. The bot
  passes the client no disk cache, so the client keeps
  `get_all_instruments` in an in-memory cache with no expiry. The legacy
  lookup read the same cached list. An instrument the broker adds after
  startup is therefore still unknown until a restart, as before. A failed
  fetch is not cached, so the next signal tries again.
- An empty instrument list lists no symbol, so every signal is refused as
  `UnknownSymbol`. The client's own lookup raised a `KeyError` there.
- "Normal: Locked" now means that the checks passed and positions are about
  to be touched. A failure while reading the balance never printed it. A
  failure during the lookup no longer prints it either, because the lookup
  is now one of the checks.

## Alternatives considered

- **Catch `ValueError` from the client's lookup.** Rejected: it would turn
  an outage that answers with an HTML page or an empty body into "unknown
  symbol" (decision 3).
- **Match the client's message exactly** (`type is ValueError` and the
  pinned text). It would fail safe on an upgrade, as a raise rather than a
  wrong line. Rejected anyway: the instrument list answers the question
  directly, and the adapter already filters the position list the same way.
- **Report refusals through the `OperatorConsole` port inside the use
  case.** Rejected: step 5's inbound adapter should be able to report a
  refusal to the caller too, so the use case returns it and the caller
  chooses.

  *Update:* the inbound adapter exists since step 5
  ([ADR 0010](0010-webhook-adapter-and-composition-root.md)). It still
  reports a refusal by one operator line only. Answering the caller is a
  behaviour change for step 6.
- **Check the broker's minimum lot and lot step** from the instrument
  details. Deferred: it needs another broker call, and the broker already
  enforces both.
