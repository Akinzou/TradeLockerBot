# Architecture

The bot is moving from a single script to a layered design
([ADR 0001](adr/0001-incremental-layered-migration.md)). The
[migration roadmap](migration-roadmap.md) tracks where it stands. This page
describes the code as it is on `master`.

## Contents

- [Layers](#layers)
- [Data flow](#data-flow)
- [Handling one signal](#handling-one-signal)
- [How a signal can end](#how-a-signal-can-end)
- [Domain model](#domain-model)
- [Application](#application)
- [Adapters](#adapters)
- [Decisions](#decisions)

## Layers

| Layer       | Package                       | May depend on      | Holds                                                         |
|-------------|-------------------------------|--------------------|---------------------------------------------------------------|
| Domain      | `tradelocker_bot.domain`      | standard library   | Trading rules as plain values and functions, with no I/O      |
| Application | `tradelocker_bot.application` | domain             | Use cases and the ports they need                             |
| Adapters    | `tradelocker_bot.adapters`    | application, domain, third-party clients, legacy `libs/` until step 5 | TradeLocker client, operator console; HTTP webhook in step 5 |
| Legacy      | `main_without_ssl.py`, `libs/` | anything          | Code not migrated yet; shrinks with every structure step      |

```mermaid
flowchart TB
    subgraph legacy [Legacy, until step 5]
        MAIN[main_without_ssl.py<br/>FastAPI webhook, login, lock]
        LIBS[libs/<br/>AsciiAlerts, URLgenerator]
    end
    subgraph adapters [tradelocker_bot.adapters]
        TLB[TradeLockerBroker]
        PC[PrintingConsole]
    end
    subgraph application [tradelocker_bot.application]
        ES[ExecuteSignal]
        PORTS[ports: Broker, OperatorConsole]
        REF[refusal: NoBalance, UnknownSymbol]
    end
    subgraph domain [tradelocker_bot.domain]
        SIG[signal: parse_signal, OpenSignal, CloseSignal, Side]
        LS[lot_sizing: LotSizing, UnusableQuantity]
        RES[result: Ok, Err]
    end
    MAIN --> TLB & PC & ES & SIG & PORTS & RES & LIBS
    TLB --> PORTS & SIG & RES
    PC --> REF & LIBS & SIG & LS
    ES --> PORTS & REF
    ES --> SIG & LS & RES
    PORTS --> SIG & RES
    REF --> LS
    SIG --> LS & RES
    LS --> RES
    TLB & MAIN --> CLIENT[(tradelocker client)]
```

Dependencies point inwards only. `tests/test_layer_dependencies.py` enforces
this for the inner layers with an explicit allow-list:

- The domain may import its own package and a named set of pure
  standard-library modules (`dataclasses`, `enum`, `math`, `typing` and
  similar).
- The application may import the same, plus the domain.
- Anything else fails, including `datetime` (the clock), `random`, `os`, the
  adapters and every third-party package.
- The same test forbids builtins that do I/O or load code, such as `open`,
  `print` and `eval`, in both layers.

Adapters exist to depend on third-party clients, so the rule does not cover
them.

## Data flow

What happens to one alert, from TradingView to the broker. Text from the
webhook becomes a typed signal at the first step and stays typed from then
on.

```mermaid
flowchart LR
    TV[TradingView alert] -- "POST, 7 lines of text" --> WH[webhook route<br/>main_without_ssl.py]
    WH -- "200 OK at once" --> TV
    WH -- "lines, in a background thread" --> P[parse_signal<br/>domain]
    P -- "Err(InvalidSignal)" --> CON[PrintingConsole<br/>stdout]
    P -- "Ok(OpenSignal or CloseSignal)" --> LOCK{{global lock}}
    LOCK --> UC[ExecuteSignal<br/>application]
    UC -- "Broker port" --> TLB[TradeLockerBroker<br/>adapter]
    TLB -- "HTTPS" --> API[(TradeLocker API)]
    UC -- "OperatorConsole port" --> CON
    UC -- "Err(Refusal)" --> CON
    UC -- "Err(BrokerFailure)" --> RAISE[re-raised in the thread]
```

| Value                         | Made by                    | Read by                                   |
|-------------------------------|----------------------------|-------------------------------------------|
| webhook lines (`list[str]`)   | FastAPI route              | `parse_signal`                            |
| `OpenSignal` / `CloseSignal`  | `parse_signal`             | `ExecuteSignal`                           |
| `InvalidSignal`               | `parse_signal`             | `PrintingConsole.rejected`                |
| balance (`float` or `None`)   | `TradeLockerBroker`        | `ExecuteSignal`, then `LotSizing`         |
| quantity (`float`)            | `LotSizing.quantity_for`   | `Broker.place_market_order`               |
| instrument id (`int` or `None`) | `TradeLockerBroker`      | `ExecuteSignal`                           |
| `Refusal`                     | `ExecuteSignal`, `LotSizing` | `PrintingConsole.rejected`              |
| `BrokerFailure`               | `TradeLockerBroker`        | the legacy handler, which re-raises it    |

## Handling one signal

### `open`

```mermaid
sequenceDiagram
    autonumber
    participant H as legacy handler
    participant UC as ExecuteSignal
    participant B as Broker (TradeLockerBroker)
    participant C as OperatorConsole
    H->>H: parse_signal(lines) = OpenSignal
    H->>H: acquire lock
    H->>UC: execute(signal)
    UC->>B: account_balance()
    B-->>UC: Ok(1000.0)
    UC->>UC: sizing.quantity_for(1000.0) = Ok(0.1)
    UC->>B: instrument_id("XAUUSD")
    B-->>UC: Ok(101)
    UC->>C: locked()
    loop until the broker lists no position on 101
        UC->>B: open_position_count(101)
        B-->>UC: Ok(n)
        loop n times
            UC->>B: request_close(101)
            UC->>C: closing("XAUUSD")
        end
    end
    loop until the broker returns an order id
        UC->>B: place_market_order(101, 0.1, side, sl, tp)
        B-->>UC: Ok(order id or None)
    end
    UC->>C: order_placed(id)
    UC->>C: unlocked()
    UC-->>H: Ok(None)
    H->>H: release lock
```

Steps 4 to 8 can end the signal early (ADR 0009). No balance, an unusable
quantity or an unknown symbol is a `Refusal`. A call that fails is a
`BrokerFailure`. Either way nothing has been closed yet. The close loop and
the order retry still have no delay or limit; the roadmap lists both as
defects for step 6.

### `close`

```mermaid
sequenceDiagram
    autonumber
    participant H as legacy handler
    participant UC as ExecuteSignal
    participant B as Broker
    participant C as OperatorConsole
    H->>H: parse_signal(lines) = CloseSignal
    H->>H: acquire lock
    H->>UC: execute(signal)
    UC->>B: instrument_id("XAUUSD")
    B-->>UC: Ok(101)
    UC->>C: locked()
    loop until the broker lists no position on 101
        UC->>B: open_position_count(101)
        UC->>B: request_close(101), once per row
        UC->>C: closing("XAUUSD")
    end
    UC->>C: unlocked()
    UC-->>H: Ok(None)
    H->>H: release lock
```

`close` sizes nothing, so it reads no balance (ADR 0008).

## How a signal can end

```mermaid
stateDiagram-v2
    [*] --> Received
    Received --> Rejected: payload error (InvalidSignal)
    Received --> Locked: valid signal
    Locked --> Refused: no balance, unusable quantity, unknown symbol
    Locked --> Failed: broker call failed before any close
    Locked --> Working: checks passed, Normal Locked line
    Working --> Failed: broker call failed while closing or ordering
    Working --> Handled: Normal Unlocked line
    Rejected --> [*]: one red line, no broker call, no lock
    Refused --> [*]: one red line, nothing closed
    Failed --> [*]: client exception re-raised in the thread
    Handled --> [*]
```

| End      | Broker calls          | Positions touched  | Operator sees                 | Thread         |
|----------|-----------------------|--------------------|-------------------------------|----------------|
| Rejected | none                  | no                 | `Signal rejected: line N ...` | ends normally  |
| Refused  | balance and/or lookup | no                 | `Signal rejected: ...`        | ends normally  |
| Failed   | up to the failing one | possibly closed    | the client's traceback        | raises         |
| Handled  | all                   | replaced or closed | `Normal: Locked` ... `Unlocked` | ends normally |

The webhook answers `200 OK` before any of this, so the caller never learns
the outcome. That is a known defect, and step 6 changes it.

## Domain model

- `parse_signal` turns the webhook's lines into an `OpenSignal` or a
  `CloseSignal`, or returns the first `InvalidSignal`. It runs before any
  broker call ([ADR 0008](adr/0008-validate-the-signal-before-any-broker-call.md)).
  An `OpenSignal` already holds the `Side` to trade, with the inversion
  applied.
- `LotSizing` is the position size per unit of account balance, parsed from
  the webhook's `<lot>/<balance step>` field. Both numbers must be positive
  and finite, and the constructor refuses anything else. `quantity_for`
  returns the rounded lots for a balance. If that number is not finite or
  not above zero, it returns `UnusableQuantity` instead
  ([ADR 0009](adr/0009-refuse-what-the-broker-rules-out-before-closing.md)).
- `Side` is `buy` or `sell`, with its `opposite`.
- `Ok` / `Err` (`Result`) is an outcome returned as a value. A result refuses
  truth testing, so a forgotten unwrap fails loudly
  ([ADR 0006](adr/0006-result-at-the-broker-boundary.md)).

## Application

[ADR 0005](adr/0005-execute-signal-use-case-and-ports.md) describes the
design.

- `ExecuteSignal` runs one valid signal.
  - `close` looks up the instrument and closes its positions.
  - `open` reads the balance, sizes the position and looks up the
    instrument. Only then does it close the instrument's positions and place
    a market order.
  - The instrument is looked up once.
  - The legacy close loop and order retry are kept. The roadmap lists them
    as defects.
- `execute` returns `Ok(None)`, a `Refusal` or the first `BrokerFailure`.
  - A `Refusal` (`NoBalance`, `UnknownSymbol`, `UnusableQuantity`) means the
    broker answered and ruled the signal out. It always comes before any
    close request (ADR 0009).
  - A `BrokerFailure` means a broker call did not answer. It holds the
    client's own exception (ADR 0006).
- `Broker` and `OperatorConsole` are its ports, one per process boundary.
  - `Broker.account_balance` returns `Ok(None)` when the answer holds no
    number.
  - `Broker.instrument_id` returns `Ok(None)` for a name the broker does not
    list. Its `Err` means only that the broker did not answer.

## Adapters

- `TradeLockerBroker` implements `Broker` over the `tradelocker` client.
  - Each method makes the legacy handler's call with the same arguments.
    The exception is the instrument lookup, which reads the instrument list
    rather than parsing the client's `ValueError` (ADR 0009).
  - Only the client call runs inside the exception guard. A fault in the
    adapter's own handling of the answer raises, so it cannot pose as an
    outage.
- `PrintingConsole` implements `OperatorConsole` as the legacy coloured
  stdout lines.
  - Its `rejected` prints one red line for an `InvalidSignal` or a
    `Refusal`, using the same "found, expected" shape for both.
  - Webhook text in that line is escaped with `repr` and cut after 40
    characters.
- `main_without_ssl.py` still receives the webhook, logs in and holds the
  lock. It parses the payload before the lock and runs a valid signal inside
  it.
  - A rejection or a refusal gets one operator line.
  - A broker failure is re-raised as the client's own exception, so the
    webhook thread fails as before.
  - Step 5 moves this into an inbound adapter and a composition root.

## Decisions

| ADR | Decision |
|-----|----------|
| [0001](adr/0001-incremental-layered-migration.md) | Migrate step by step, behind characterization tests |
| [0002](adr/0002-ci-quality-gates.md) | CI quality gates and image publishing |
| [0003](adr/0003-publish-with-workflow-token.md) | Publish the image with the workflow token |
| [0004](adr/0004-flat-application-package.md) | A flat `tradelocker_bot` package next to the legacy entrypoint |
| [0005](adr/0005-execute-signal-use-case-and-ports.md) | Execute-signal use case behind broker and console ports |
| [0006](adr/0006-result-at-the-broker-boundary.md) | Broker failures as a Result |
| [0007](adr/0007-locked-runtime-dependencies.md) | Lock every runtime dependency |
| [0008](adr/0008-validate-the-signal-before-any-broker-call.md) | Validate the whole signal before any broker call |
| [0009](adr/0009-refuse-what-the-broker-rules-out-before-closing.md) | Refuse what the broker rules out before closing anything |
