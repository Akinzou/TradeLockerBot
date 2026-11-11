# ADR 0004: A flat `tradelocker_bot` package next to the legacy entrypoint

- Status: Accepted
- Date: 2026-11-11

## Context

Migrated code needs a home that both the legacy entrypoint
(`main_without_ssl.py`) and the tests can import. The image copies the whole
repository into `/app` and runs `python main_without_ssl.py` from there,
without installing the project as a package.

## Decision

New code lives in a top-level `tradelocker_bot/` package, split into layers:
`domain/` now, with `application/` and `adapters/` as later roadmap steps
create them. A fitness test (`tests/test_domain_dependencies.py`) allows the
domain to import only its own package and standard-library modules that do no
I/O and do not read the clock. It is an allow-list, so a new third-party
package or layer fails CI without anyone having to list it.

## Consequences

- The image needs no change: `/app` is the working directory, so
  `tradelocker_bot` imports the same way the legacy `libs/` does.
- CI smoke-runs the entrypoint inside the built image. The tests run from the
  repository root on the runner's Python, so they cannot detect a package
  that is missing from, or broken in, the image.

## Alternatives considered

- **import-linter forbidden contract.** Rejected for the domain rule: a
  forbidden contract lists packages to block, so any library not on the list
  passes. Reconsider import-linter's layers contract once the application and
  adapter layers exist.

- **`src/` layout.** Rejected for now: it only works once the image installs
  the project (`pip install .`). That changes the image build and the frozen
  container contract in a step that is meant to be structure-only. Revisit
  when the entrypoint is replaced (roadmap step 5).
