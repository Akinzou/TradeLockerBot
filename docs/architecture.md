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
`tests/test_layer_dependencies.py`, an explicit allow-list: the domain may
import its own package and a named set of pure standard-library modules
(`dataclasses`, `enum`, `math`, `typing` and similar). Anything else fails,
including `datetime` (the clock), `random`, `os` and every third-party
package. The same test forbids builtins that do I/O or load code, such as
`open`, `print` and `eval`. Rules for the outer layers are added together with
those layers.

## Domain model

- `LotSizing`: position size per unit of account balance, parsed from the
  webhook's `<lot>/<divider>` field. It keeps the legacy semantics exactly,
  including accepting nonsensical values, until roadmap step 3 adds validation.
