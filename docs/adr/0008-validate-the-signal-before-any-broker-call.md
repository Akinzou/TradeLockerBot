# ADR 0008: Validate the whole signal before any broker call

- Status: Accepted
- Date: 2026-11-11

## Context

Before this step the handler read the webhook lines field by field and the
use case validated them only as far as it got. The roadmap's defect list
pinned what that cost:

- With `Invert`, any direction other than exactly `buy` (`Buy`, `BUY`)
  opened a **buy**. With `NonInvert` it was sent to the broker unchanged.
- An invalid `Invert`/`NonInvert` flag stopped an `open` only **after** the
  instrument's positions were closed, leaving the account flat.
- A malformed lot crashed the handler after the balance read. A lot that
  parsed but made no sense (`0/100`, `-0.01/100`, `inf/100`, `nan/100`) was
  sent to the broker as quantity 0, negative, infinite or NaN.
- An unknown action, including `Open` or ` open`, was silently ignored.
- A truncated payload or a non-numeric take profit or stop loss raised an
  `IndexError` or `ValueError` in the webhook thread.
- `close` needed valid lot, take profit, stop loss and inversion lines that it
  never used.

## Decision

1. **The payload is parsed into a domain signal before the lock and before
   any broker call.** `parse_signal` in `tradelocker_bot.domain.signal`
   returns `Ok(OpenSignal | CloseSignal)` or `Err(InvalidSignal)`. The use
   case only ever receives a valid signal, and `ExecuteSignal.execute` keeps
   `BrokerFailure` as its only error (ADR 0006).
2. **Rejection.** An `Err` is reported by one red operator line, for example
   `Signal rejected: line 2 (direction) is 'long', expected buy or sell`. It
   makes no broker call, does not take the lock and raises nothing, so the
   webhook thread ends normally. The owner chose this over also raising: the
   line says everything a traceback would. Only the first line that stops the
   signal is reported. The webhook still answers `200 OK` before handling.
   Answering the caller is step 6. *Update:* step 6k kept the answer as it
   is: it acknowledges receipt, not the outcome
   ([ADR 0023](0023-the-webhook-answer-acknowledges-receipt.md)).
3. **Case and surrounding spaces.** The owner decided that they do not change
   what a direction (line 2) or an action (line 6) means. `Buy`, ` SELL `,
   `Open` and `close ` are accepted. Anything else is rejected. Line 7 was not
   part of that decision and stays exact: `Invert` or `NonInvert`.
4. **`close` reads only what it uses.** The owner decided this too: junk in a
   line `close` never reads must not keep a position open. `close` needs
   lines 1 and 6 only, so a six-line `close` is complete. Because it sizes
   nothing, `close` **no longer reads the account balance**. That removes one
   broker call from a valid signal, and the call-sequence pins change
   accordingly.
5. **`open` needs every line**, read in order 2, 3, 4, 5, 7 after the symbol
   and the action:
   - **Direction:** `buy` or `sell` as in item 3.
   - **Lot:** `<lot>/<balance step>`, both positive and finite. The rule sits
     in `LotSizing`'s constructor, so no code path can build a sizing that is
     zero, negative, infinite or NaN.
   - **Take profit and stop loss:** whatever `int()` accepts.
   - **Inversion:** resolved here into the side to trade, so it can no
     longer fail after a close.
6. **What is not on the defect list is kept.** Input that worked before stays
   accepted, so a change here cannot break a running strategy unannounced:
   - spaces around the lot numbers;
   - signs, spaces, zero and negative values in the offsets;
   - lines after the seventh, which are still ignored;
   - the symbol, which is used verbatim; only a blank one is rejected.
7. **The rejection line escapes the value.** The value comes from the
   webhook, and `splitlines()` keeps control characters such as ESC in a
   line. The console prints it with `repr` and cuts it after 40 characters,
   so a payload cannot colour, rewrite or flood the operator's log.

## Not in this step

Some rejections need the broker's answer. They stay pinned as defects until
roadmap step 3b, which must refuse each of them before the first close
request:

- an account state without a balance, still a `TypeError`;
- an unknown symbol, still the client's `ValueError`, raised after the
  balance read;
- a quantity that is unusable once the balance is known: zero when the
  balance is too small for it to round above zero, infinite when the product
  overflows (`1e306/1`). Both are still sent to the broker.

*Update:* step 3b
([ADR 0009](0009-refuse-what-the-broker-rules-out-before-closing.md)) refuses
all three before any close request. A broker-side refusal is a second error
kind of `execute`, next to `BrokerFailure`, so decision 1's "only error" no
longer holds.

## Consequences

- The frozen webhook contract changes: lines 2 and 6 now ignore case and
  surrounding spaces, and `close` needs lines 1 and 6 only. Every alert that
  was handled correctly before is still handled the same way, except that
  `close` no longer reads the balance.
- **Some alerts that did nothing before now trade.** An action such as
  `Open` or `close ` used to be ignored, and a `close` with an invalid unused
  line used to crash. Both now act. A strategy that relied on either, knowingly
  or not, changes behaviour on upgrade. The README's Updating section says so.
- Every input error is visible to the operator by line number, in one line,
  instead of as a traceback or not at all.
- An invalid alert does not wait for the lock and does not hold it, so it
  cannot delay a valid one.
- ADR 0006's condition for step 5 is met for input errors. The missing
  balance still raises from the use case until step 3b.
- `order_side` is gone. `Side` and its `opposite` replace it, and the
  broker port and the retry line take a `Side` instead of a string.

## Alternatives considered

- **Validate inside the use case and return `Err(InvalidSignal)` from
  `execute`.** Rejected: the use case would accept text it cannot act on, and
  its callers would branch on two unrelated error types. Parsing at the edge
  gives the use case a type that cannot be invalid.
- **Report every invalid line at once.** Rejected for now: one line is easier
  to read in a container log, and fixing the first usually reveals the rest.
- **Accept `invert`/`noninvert` too.** Not decided by the owner, and nothing
  sends them today. A later step can widen it if needed.
