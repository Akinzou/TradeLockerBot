# Architecture

The bot is moving from a single script to a layered design
([ADR 0001](adr/0001-incremental-layered-migration.md)). The
[migration roadmap](migration-roadmap.md) tracks where it stands. This page
describes the code as it is on `master`.

## Contents

- [Layers](#layers)
- [Startup](#startup)
- [Data flow](#data-flow)
- [Handling one signal](#handling-one-signal)
- [How a signal can end](#how-a-signal-can-end)
- [Domain model](#domain-model)
- [Application](#application)
- [Adapters](#adapters)
- [Composition root](#composition-root)
- [Decisions](#decisions)

## Layers

| Layer             | Package                            | May depend on                                   | Holds                                                          |
|-------------------|------------------------------------|-------------------------------------------------|----------------------------------------------------------------|
| Domain            | `tradelocker_bot.domain`           | standard library                                | Trading rules as plain values and functions, with no I/O       |
| Application       | `tradelocker_bot.application`      | domain                                          | Use cases and the ports they need                              |
| Adapters          | `tradelocker_bot.adapters`         | application, domain, third-party clients        | TradeLocker client and login, operator console, HTTP webhook, signal handler |
| Composition root  | `tradelocker_bot.composition_root` | everything above                                | Start arguments, banners, wiring, the lock, the server start   |
| Entrypoint        | `main_without_ssl.py`              | the composition root                            | The container's command; calls `main()` and nothing else       |

Every arrow below is an import in the code. The entrypoint keeps its name
because the container command is part of the frozen contract
([roadmap](migration-roadmap.md#frozen-contract)).

```mermaid
flowchart TB
    EP[main_without_ssl.py<br/>container command]
    CR[composition_root<br/>parse_args, main, build_signal_handler]
    subgraph adapters [tradelocker_bot.adapters]
        WH[webhook<br/>create_app]
        SH[signal_handler<br/>SignalHandler]
        TLB[tradelocker_broker<br/>TradeLockerBroker, log_in]
        PC[console<br/>PrintingConsole]
        AA[ascii_alerts<br/>colours, banners]
        WP[webhook_path<br/>random_webhook_path]
    end
    subgraph application [tradelocker_bot.application]
        ES[ExecuteSignal]
        PORTS[ports: Broker, OperatorConsole, BrokerFailure]
        REF[refusal: NoBalance, UnknownSymbol]
    end
    subgraph domain [tradelocker_bot.domain]
        SIG[signal: parse_signal, OpenSignal, CloseSignal, Side]
        LS[lot_sizing: LotSizing, UnusableQuantity]
        RES[result: Ok, Err]
    end
    EP --> CR
    CR --> WH & SH & TLB & PC & AA & WP & ES
    SH --> PC & ES & PORTS & RES & SIG
    TLB --> PORTS & RES & SIG
    PC --> AA & REF & LS & SIG
    ES --> PORTS & REF & LS & RES & SIG
    PORTS --> RES & SIG
    REF --> LS
    SIG --> LS & RES
    LS --> RES
    WH --> FASTAPI[(FastAPI)]
    CR --> UVICORN[(uvicorn)]
    TLB --> CLIENT[(tradelocker client)]
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

Adapters exist to depend on third-party clients, so the allow-list does not
cover them. The same test keeps them inward of the composition root: an
adapter may import neither `composition_root` nor `main_without_ssl`, so no
adapter can reach another's wiring, such as the shared lock or the
logged-in client, behind the root's back
([ADR 0010](adr/0010-webhook-adapter-and-composition-root.md)).

## Startup

```mermaid
sequenceDiagram
    autonumber
    participant EP as main_without_ssl.py
    participant CR as composition_root.main
    participant TB as tradelocker_broker.log_in
    participant WH as webhook.create_app
    participant U as uvicorn
    EP->>CR: main()
    CR->>CR: parse_args (exit 2 on a bad argument,<br/>a --url without a leading / or with a brace)
    opt --url generate
        CR->>CR: print the URL banner and random_webhook_path()
    end
    CR->>CR: print the greeting
    CR->>CR: int(acc_num), int(acc_id)
    CR->>TB: log_in(env, credentials, selectors)
    TB-->>CR: TLAPI client (or the client's exception)
    CR->>CR: build_signal_handler(client, one Lock)
    CR->>WH: create_app(url, handler.handle)
    WH-->>CR: FastAPI app
    CR->>U: run(app, host="0.0.0.0", port)
```

A bad argument stops at step 2, a bad account selector at step 5, and a
failed login at step 6. Each leaves every later step undone, so the server
never starts on a half-built bot.

## Data flow

What happens to one alert, from TradingView to the broker. Text from the
webhook becomes a typed signal at the first step and stays typed from then
on.

```mermaid
flowchart LR
    TV[TradingView alert] -- "POST, 7 lines of text" --> WH[webhook route<br/>adapters.webhook]
    WH -- "200 OK at once" --> TV
    WH -- "lines, in a background thread" --> SH[SignalHandler<br/>adapters.signal_handler]
    SH --> P[parse_signal<br/>domain]
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
| webhook lines (`list[str]`)   | `create_app`'s route       | `SignalHandler.handle`, then `parse_signal` |
| `OpenSignal` / `CloseSignal`  | `parse_signal`             | `ExecuteSignal`                           |
| `InvalidSignal`               | `parse_signal`             | `PrintingConsole.rejected`                |
| balance (`float` or `None`)   | `TradeLockerBroker`        | `ExecuteSignal`, then `LotSizing`         |
| quantity (`float`)            | `LotSizing.quantity_for`   | `Broker.place_market_order`               |
| instrument id (`int` or `None`) | `TradeLockerBroker`      | `ExecuteSignal`                           |
| `Refusal`                     | `ExecuteSignal`, `LotSizing` | `PrintingConsole.rejected`              |
| `BrokerFailure`               | `TradeLockerBroker`        | `SignalHandler`, which re-raises its cause |

## Handling one signal

### `open`

```mermaid
sequenceDiagram
    autonumber
    participant H as SignalHandler
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
    participant H as SignalHandler
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
  - `log_in`, in the same module, logs in to the demo or live server, on the account that
    `--acc_num` or `--acc_id` names. It refuses both at once before sending
    any credentials.
- `PrintingConsole` implements `OperatorConsole` as the legacy coloured
  stdout lines.
  - Its `rejected` prints one red line for an `InvalidSignal` or a
    `Refusal`, using the same "found, expected" shape for both.
  - Webhook text in that line is escaped with `repr` and cut after 40
    characters.
- `create_app` (`webhook`) is the inbound HTTP adapter. It serves the
  webhook path, splits the body into lines and starts one thread per
  request. It serves nothing else: no OpenAPI schema and no docs pages,
  because the schema would name the secret path
  ([ADR 0011](adr/0011-serve-no-api-docs.md)). It redirects nothing: a path
  one slash away answers `404`, because the redirect pointed senders at
  plain `http://` ([ADR 0013](adr/0013-no-trailing-slash-redirect.md)).
- `SignalHandler` runs one request's lines. It parses them before the lock
  and runs a valid signal inside it.
  - A rejection or a refusal gets one operator line.
  - A broker failure is re-raised as the client's own exception, so the
    webhook thread fails as before.
- `ascii_alerts` holds the console's colours and the startup banners, and
  `webhook_path` makes the random path for `--url generate`, from
  `secrets` ([ADR 0012](adr/0012-generate-the-webhook-path-with-secrets.md)).

## Composition root

`tradelocker_bot/composition_root.py` is the only module that knows every
layer ([ADR 0010](adr/0010-webhook-adapter-and-composition-root.md)).

- `main()` reads the arguments, prints the banners, logs in, builds the
  app and starts the server, in the order the [startup](#startup) diagram
  shows.
- It creates the one lock that every request shares.
- `webhook_url` checks `--url` as the arguments are read: `generate` or a
  path that starts with `/` and has no `{` or `}`, so the route is matched
  as written. Anything else exits with status `2`, like any bad argument,
  and the message leaves the value out
  ([ADR 0014](adr/0014-require-a-leading-slash.md),
  [ADR 0015](adr/0015-refuse-braces-in-the-webhook-path.md)).
- `build_signal_handler(client, lock)` builds the console, the broker adapter, the
  use case and the handler once, at startup. The characterization tests
  build theirs through the same function.
- `main_without_ssl.py` imports `main` and calls it, and does nothing else.

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
| [0010](adr/0010-webhook-adapter-and-composition-root.md) | Inbound webhook adapter and a composition root |
| [0011](adr/0011-serve-no-api-docs.md) | Serve no API docs, so no page names the webhook path |
| [0012](adr/0012-generate-the-webhook-path-with-secrets.md) | Generate the webhook path with `secrets` |
| [0013](adr/0013-no-trailing-slash-redirect.md) | No trailing-slash redirect on the webhook |
| [0014](adr/0014-require-a-leading-slash.md) | Refuse a webhook path without a leading slash |
| [0015](adr/0015-refuse-braces-in-the-webhook-path.md) | Refuse braces in the webhook path |
