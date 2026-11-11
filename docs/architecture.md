# Architecture

The bot is mid-migration from a single script to a layered design
([ADR 0001](adr/0001-incremental-layered-migration.md)); the current state is
tracked in the [migration roadmap](migration-roadmap.md).

## Layers

| Layer       | Package                       | May depend on      | Holds                                                         |
|-------------|-------------------------------|--------------------|---------------------------------------------------------------|
| Domain      | `tradelocker_bot.domain`      | standard library   | Trading rules as plain values and functions, with no I/O      |
| Application | `tradelocker_bot.application` | domain             | Use cases and the ports they need (step 4, not yet created)   |
| Adapters    | `tradelocker_bot.adapters`    | application, domain | TradeLocker API client, HTTP webhook (steps 4 and 5)         |
| Legacy      | `main_without_ssl.py`, `libs/` | anything          | Code not migrated yet; shrinks with every structure step      |

Dependencies point inwards only. The domain rule is enforced by
`tests/test_domain_dependencies.py`, an allow-list: the domain may import its
own package and standard-library modules that do no I/O and do not read the
clock (no `os`, `socket`, `time`, `random`, and so on). Rules for the outer
layers are added together with those layers.

## Domain model

- `LotSizing`: position size per unit of account balance, parsed from the
  webhook's `<lot>/<divider>` field. It keeps the legacy semantics exactly,
  including accepting nonsensical values, until roadmap step 3 adds validation.
