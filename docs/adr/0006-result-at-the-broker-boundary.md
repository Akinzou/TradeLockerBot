# ADR 0006: Broker failures as a Result at the port and use-case boundary

- Status: Accepted
- Date: 2026-11-11

## Context

After step 4 ([ADR 0005](0005-execute-signal-use-case-and-ports.md)), a broker
failure was an exception. It travelled from the TradeLocker client through
the `Broker` adapter and the `ExecuteSignal` use case to the webhook thread.
Nothing in a signature said that any of the five broker calls could fail. A
caller could forget the failure without any sign until production.

Roadmap step 4b makes the failure a value at the boundary. It is a structure
step: ADR 0001's equivalence rule applies, and `tests/characterization` stays
unchanged. Step 2f pinned a failure at every broker call first. Those pins
check the calls made, the console lines, the lock release, and that the
handler re-raises the client's own exception object.

## Decision

1. **`Result` in the domain.** `tradelocker_bot.domain.result` defines
   `Ok(value)`, `Err(error)` and `Result = Union[Ok[T], Err[E]]`, as frozen
   dataclasses. It lives in the domain because the domain is the only layer
   every other layer may import; step 3's validation will return it too.
   Callers branch with `isinstance` or `match`. A result **refuses truth
   testing** (`bool()` raises `TypeError`). `Ok(0)` and `Ok(None)` would
   otherwise be truthy, and `while not order_id:` on an unwrapped result
   would stop retrying silently.
2. **Broker port.** Every `Broker` method returns `Result[T, BrokerFailure]`.
   `BrokerFailure(cause)` holds the client's exception object as raised.
3. **Adapter.** `TradeLockerBroker` turns any `Exception` from a client call
   into `Err(BrokerFailure(error))`. Only the client call is wrapped: the
   adapter's own handling of the answer (reading the balance field, counting
   rows) stays outside, so a bug there raises instead of posing as a broker
   outage. The client raises its own
   `TLAPIException`, a bare `ValueError` for an unknown symbol, and whatever
   `requests` and pandas raise underneath, so no narrower list is complete.
   `BaseException` (interrupts, interpreter exit) is not caught.
4. **Use case.** `ExecuteSignal.execute` returns `Ok(None)`, or the first
   broker failure at once. It makes no further broker call and writes no
   `unlocked` line, exactly where the exception used to leave.
5. **Legacy delegate.** `handle_position_normal` raises `result.error.cause`
   inside the lock. That is the same object, so the webhook thread fails with
   the same type, message and attributes as before.

   The traceback is not the same. It still runs from the delegate down
   through the client to the raise site, but the use-case frames in between
   are gone, because the exception left them as a value. ADR 0001's
   equivalence rule covers type and outcome, not frames. The cost is
   diagnostic: a failed instrument lookup no longer shows whether it was the
   first or the second one. Logging the failure inside the use case would
   recover that, and belongs with failure reporting in step 5.

   *Update:* step 5 ([ADR 0010](0010-webhook-adapter-and-composition-root.md))
   was a structure step, so it moved the re-raise into
   `SignalHandler.handle` unchanged. Failure logging and reporting moved to
   step 6.

### Kept out of the Result in this step

- **Lot and inversion errors** (`ValueError`, `ZeroDivisionError`, and the
  `TypeError` from a missing balance) still raise from the domain. They are
  input validation. Turning them into values here would mean catching
  `TypeError` and `ZeroDivisionError` around domain calls, which would also
  hide real bugs. Step 3 validates the whole signal before any broker call
  and returns its own Result.
- **The console port** still returns `None`. The only way writing to stdout
  can fail is an infrastructure fault the use case cannot handle (a closed
  pipe). A Result there would add a branch to every line, with no recovery
  to put in it. If the console becomes a remote sink, its port gets a Result
  then.

## Consequences

- Every broker call's failure is visible in its signature. The type checker
  and the unit tests can follow each one.
- The use case's unit tests check, for an `Err` at every port call, the
  exact calls and lines before it. They also check that the returned failure
  holds the original exception.
- Behaviour is unchanged. The webhook thread still dies with the client's
  exception. Reporting failures to the operator instead is a behaviour change
  for step 5 or 6.

  *Update:* step 6. Step 5 ([ADR 0010](0010-webhook-adapter-and-composition-root.md))
  changed structure only.
- `execute`'s return type covers broker failures only. Until step 3, invalid
  input (a malformed lot, an unknown `isInvert`, a missing balance) still
  raises from the use case, after any positions were already closed in the
  `isInvert` case. A caller that stops re-raising, such as step 5's inbound
  adapter, must therefore come after step 3 or keep handling those
  exceptions.

  *Update:* step 3 (ADR 0008) removed every input error from the use case.
  The missing balance still raises until step 3b, so step 5 follows 3b.

  *Update:* step 3b (ADR 0009) refuses the missing balance, the unknown
  symbol and the unusable quantity as `Err(Refusal)`. No signal and no
  well-formed broker answer raises from the use case any more, so step 5
  can start. An answer the adapter cannot read still raises, on purpose. `execute` now returns
  `Result[None, BrokerFailure | Refusal]`. The legacy handler re-raises only
  a `BrokerFailure` and prints a refusal.

## Alternatives considered

- **A third-party Result library** (`returns`, `result`). Rejected: the layer
  rule admits no third-party package in the domain, and two dataclasses cover
  what is needed.
- **Re-raise a new exception in the delegate** (`raise BrokerError(...) from
  cause`). Rejected: it changes the type the thread dies with, which the pins
  forbid in a structure step.
- **Catch only `TLAPIException` in the adapter.** Rejected: an unknown symbol
  and network errors would still escape as exceptions, so the port's
  signature would make a promise the adapter does not keep.
