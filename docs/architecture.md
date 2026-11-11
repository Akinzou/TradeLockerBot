# Architecture

The bot is mid-migration from a single script to a layered design
([ADR 0001](adr/0001-incremental-layered-migration.md)); the current state is
tracked in the [migration roadmap](migration-roadmap.md).

## Layers

| Layer       | Package                       | May depend on      | Holds                                                         |
|-------------|-------------------------------|--------------------|---------------------------------------------------------------|
| Domain      | `tradelocker_bot.domain`      | standard library   | Trading rules as plain values and functions, with no I/O      |
| Application | `tradelocker_bot.application` | domain             | Use cases and the ports they need                             |
| Adapters    | `tradelocker_bot.adapters`    | application, domain, third-party clients, legacy `libs/` until step 5 | TradeLocker client, operator console; HTTP webhook in step 5 |
| Legacy      | `main_without_ssl.py`, `libs/` | anything          | Code not migrated yet; shrinks with every structure step      |

Dependencies point inwards only. `tests/test_layer_dependencies.py` enforces
this for the inner layers with an explicit allow-list: the domain may import
its own package and a named set of pure standard-library modules
(`dataclasses`, `enum`, `math`, `typing` and similar); the application may
also import the domain. Anything else fails, including `datetime` (the clock),
`random`, `os`, the adapters and every third-party package. The same test
forbids builtins that do I/O or load code, such as `open`, `print` and
`eval`, in both layers. Adapters exist to depend on third-party clients, so
they are outside the rule.

## Domain model

- `parse_signal`: turns the webhook's lines into an `OpenSignal` or a
  `CloseSignal`, or the first `InvalidSignal`, before any broker call
  ([ADR 0008](adr/0008-validate-the-signal-before-any-broker-call.md)). An
  `OpenSignal` already holds the `Side` to trade, with the inversion applied.
- `LotSizing`: position size per unit of account balance, parsed from the
  webhook's `<lot>/<balance step>` field. Both numbers must be positive and
  finite; the constructor refuses anything else.
- `Side`: `buy` or `sell`, and its `opposite`.
- `Ok` / `Err` (`Result`): an outcome returned as a value. A result refuses
  truth testing, so a forgotten unwrap fails loudly
  ([ADR 0006](adr/0006-result-at-the-broker-boundary.md)).

## Application

[ADR 0005](adr/0005-execute-signal-use-case-and-ports.md) describes the
design.

- `ExecuteSignal` runs one valid signal. `close` closes the instrument's
  positions. `open` reads the balance, sizes the position, closes the
  instrument's positions and places a market order. It keeps the legacy order
  of broker calls otherwise, including the known defects listed in the
  roadmap.
- `Broker` and `OperatorConsole` are its ports, one per process boundary.
  `TradeLockerBroker` and `PrintingConsole` in `tradelocker_bot.adapters`
  implement them.
- Every `Broker` call returns a `Result`: a client exception comes back as
  `Err(BrokerFailure)` holding that exception, and `ExecuteSignal` returns
  the first one at once. A missing balance still raises from the lot sizing
  until step 3b.
- `main_without_ssl.py` still receives the webhook. It parses the payload
  first; a rejected signal gets one operator line and nothing else. A valid
  one runs inside the lock. On a broker failure it re-raises the client's own
  exception, so the webhook thread fails as before. Step 5 moves that into an
  inbound adapter and a composition root.
