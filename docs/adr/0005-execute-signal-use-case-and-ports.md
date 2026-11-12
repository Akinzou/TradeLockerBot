# ADR 0005: The execute-signal use case and its broker and console ports

- Status: Accepted
- Date: 2026-11-11

## Context

`handle_position_normal` in `main_without_ssl.py` mixes three things: the
order of trading steps for a signal, calls to the TradeLocker client, and
operator console output. Roadmap step 4 moves the trading steps into the
application layer. It is a structure step, so ADR 0001's equivalence rule
applies: for every input, the same broker calls with the same arguments, the
same outcome and exception type, one critical section released on raise, and
the same console lines in the same order inside that section.

The characterization suite pins all of that, including the raising paths
(roadmap step 2d), and stays unchanged.

## Decision

### Layers

- `tradelocker_bot.application` holds the `ExecuteSignal` use case, the
  `TradeSignal` input it receives, and two ports, `Broker` and
  `OperatorConsole`, as `typing.Protocol` classes. It may import only the
  domain, itself and pure standard-library modules; the fitness test enforces
  this the same way it does for the domain.

  *Update:* [ADR 0008](0008-validate-the-signal-before-any-broker-call.md)
  replaced `TradeSignal` with the domain's `OpenSignal` and `CloseSignal`,
  parsed before the use case runs.
- `tradelocker_bot.adapters` holds `TradeLockerBroker`, which wraps a
  `TLAPI` client, and `PrintingConsole`, which writes to stdout.
- Resolving the order side from the direction and the invert flag has no I/O,
  so it is a domain function, not part of a port.

### Ports

Each port is one process boundary: the broker's HTTP API and the operator's
console.

| `Broker` method                                  | TradeLocker call                                                     |
|--------------------------------------------------|----------------------------------------------------------------------|
| `account_balance()`                              | `get_account_state().get("projectedBalance")`, returned uncoerced   |
| `instrument_id(symbol)`                          | `get_instrument_id_from_symbol_name(symbol)`                         |
| `open_position_count(instrument_id)`             | `get_all_positions()`, rows for the instrument counted in the adapter |
| `request_close(instrument_id)`                   | `close_all_positions(instrument_id)`                                 |
| `place_market_order(instrument_id, quantity, side, stop_loss, take_profit)` | `create_order(..., type_="market", stop_loss_type="offset", take_profit_type="offset")` |

*Update:* since step 3b
([ADR 0009](0009-refuse-what-the-broker-rules-out-before-closing.md)), two
rows have changed:

- `account_balance()` returns `None` for any answer that is not a number.
- `instrument_id(symbol)` matches the name in `get_all_instruments()` and
  returns `None` for a name the broker does not list, so it no longer relies
  on the client's `ValueError`.

`OperatorConsole` has one method per legacy line: `locked`, `closing`,
`order_retry`, `order_placed`, `unlocked`.

*Update:* since step 6i
([ADR 0021](0021-report-a-rejected-order-and-place-it-once.md)), the order
is placed once, so `order_retry` and its line are gone, and
`OperatorConsole` gains `order_rejected`.
`place_market_order` returns an id only for an order the broker created,
and `Err(OrderRejected)` when the broker answered without creating one.

The `open_position_count` / `request_close` pair is **provisional**. It mirrors
a known defect: one close request per open row, repeated on every poll until
the broker reports none. A port shaped around the defect keeps this step
behaviour-neutral; the fix (roadmap step 6) may replace the pair with a single
close-and-confirm operation.

*Update:* since step 6j
([ADR 0022](0022-pace-the-close-loop-on-a-clock.md)), the loop pauses a
second between counts, on a new `Clock` port, and asks again only every 10
seconds. The pair stays: the use case paces the loop, so the broker port
stays a plain request and a plain count. One request per row is kept,
because whether the broker closes every row on one request was not
observed.

### Ordering kept from the legacy handler

1. The inbound side, still in `main_without_ssl.py`, reads the payload fields
   inside the lock in the legacy order: lines 1, 2, 3, `int` of line 4,
   `int` of line 5, line 7, then line 6.
2. The use case reads the balance, then parses the lot and sizes the
   quantity, then reports `locked`.
3. `close` closes positions. `open` closes positions (with its own instrument
   lookup), looks the instrument up a second time, then resolves the side, then
   places the order. The retry line uses the resolved side.
4. It reports `unlocked` only when nothing raised.

### Errors

*Superseded by [ADR 0006](0006-result-at-the-broker-boundary.md): broker
failures are now returned as a Result.*

In this step, ports raised the client's exceptions unchanged and the use
case let them propagate. The Result was kept out so that the move stayed
reviewable against the legacy handler line by line.

## Consequences

- `main_without_ssl.py` keeps `handle_position_normal` as a thin delegate that
  extracts the fields, builds the adapters and runs the use case inside the
  lock. The characterization harness keeps importing it from there.
- The use case is unit-tested against in-memory port fakes, and the adapters
  against the signature-checked `FakeTradeLocker`.
- `PrintingConsole` still uses the legacy `libs.AsciiAlerts` colours. Adapters
  may depend on legacy code until step 5 removes it.

  *Update (step 5, [ADR 0010](0010-webhook-adapter-and-composition-root.md)):*
  the colours moved to `tradelocker_bot/adapters/ascii_alerts.py`, and
  `libs/` is gone. `handle_position_normal` became `SignalHandler.handle` in
  the inbound adapter, and the harness reaches it through the composition
  root.

## Alternatives considered

- **One port method per legacy helper** (`close_positions(symbol)`,
  `place_order(...)`). Rejected: the close-polling loop and the order retry
  loop are trading decisions, and they would stay in infrastructure, out of
  reach of unit tests.
- **The adapter returns the positions DataFrame.** Rejected: it would leak
  pandas into the application layer.
- **A logger instead of a console port.** Rejected for now: the pinned output
  is plain `print` lines with colour codes, and a logger changes the format.
  Replacing the console with structured logging is a behaviour change.
