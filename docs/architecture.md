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

- `LotSizing`: position size per unit of account balance, parsed from the
  webhook's `<lot>/<divider>` field. It keeps the legacy semantics exactly,
  including accepting nonsensical values, until roadmap step 3 adds validation.
- `order_side`: the side to trade, given the alert's direction and its
  `Invert`/`NonInvert` flag. It keeps the legacy semantics too: directions are
  not validated, and `Invert` turns anything but exactly `buy` into `buy`.

## Application

[ADR 0005](adr/0005-execute-signal-use-case-and-ports.md) describes the
design.

- `ExecuteSignal` runs one alert: it reads the balance, sizes the position,
  closes the instrument's positions and, for `open`, places a market order. It
  keeps the legacy order of steps exactly, including the known defects listed
  in the roadmap.
- `Broker` and `OperatorConsole` are its ports, one per process boundary.
  `TradeLockerBroker` and `PrintingConsole` in `tradelocker_bot.adapters`
  implement them.
- `main_without_ssl.py` still receives the webhook. Inside the lock it reads
  the payload fields in the legacy order, builds the adapters and runs the use
  case. Step 5 moves that into an inbound adapter and a composition root.
