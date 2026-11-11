# Migration roadmap

This is the live state of the migration described in
[ADR 0001](adr/0001-incremental-layered-migration.md). Update it in every
migration pull request.

## Steps

| #  | Step                                                                                                                                                        | Kind      | Status                               |
|----|-------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|--------------------------------------|
| 1  | Characterization tests, CI gates, publish only from `master`                                                                                                | safety    | done                                 |
| 1a | Restore image publishing with the workflow token and report publish failures ([ADR 0003](adr/0003-publish-with-workflow-token.md))                         | safety    | blocked: owner grants package access |
| 1b | Delete the `PERSONAL_ACCESS_TOKEN` secret after the first successful publish                                                                                | safety    | todo                                 |
| 1c | Pin malformed-payload behaviour (direction case, action case, malformed lot)                                                                                | safety    | done                                 |
| 2  | Domain: lot sizing as a pure value object (the only logic identical for every input today), plus a layer import contract and an image smoke run            | structure | done                                 |
| 2a | Pin exact broker call sequences, lock coverage and operator console lines; make the domain dependency rule a true allow-list                                | safety    | done                                 |
| 2b | Pin the `tradelocker` client to the version the broker fake mirrors, checked in the built image                                                             | safety    | done                                 |
| 2c | Lock every runtime dependency (direct and transitive) and check the image against the lock                                                                  | safety    | todo                                 |
| 3  | Validate the whole signal before any broker call: strict direction, action, lot and inversion types, a Result at the boundary (own ADR). Expected pin updates: wrong-side and NonInvert-forwarding, invalid-invert-after-close, truncated payload, non-numeric take-profit, unknown action, malformed and nonsensical lot | behaviour | todo — merge only after 1a is unblocked |
| 4  | Application: execute-signal use case behind a broker port; TradeLocker adapter implements the port                                                          | structure | next                                 |
| 5  | Inbound HTTP adapter and composition root; `main_without_ssl.py` becomes a thin entrypoint                                                                  | structure | todo                                 |
| 6  | Remaining behaviour changes from the defect list below, one pull request and one ADR each                                                                   | behaviour | todo                                 |

Structure steps must keep `tests/characterization/` green with **unchanged
assertions**. Only the seam may move, meaning the module the tests import
or patch, and the pull request must call it out.

## Frozen contract

These stay unchanged until an ADR changes them:

- Docker image name `ghcr.io/akinzou/tradelocker_bot:latest`, and
  `main_without_ssl.py` as the container command.
- Container environment variables `username`, `password`, `server`, `env`,
  `url`, `acc_num`, `acc_id`.
- Default webhook path `/strategy`, `url=generate` for a random path, and port
  443 by default.
- The webhook body: seven newline-separated lines (symbol, `buy`/`sell`,
  `<lot>/<divider>`, take-profit offset, stop-loss offset, `open`/`close`,
  `Invert`/`NonInvert`).

## Known defects (fixed in behaviour steps 3 and 6, never during restructuring)

| Defect                                                                                                                                                              | Pinned by                                                                   |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| **Wrong-side trade:** with `Invert`, any direction other than exactly `buy` (e.g. `Buy`) opens a *buy*. With `NonInvert` it is forwarded unvalidated after the existing position was closed; the broker's answer is unverified, and a rejection leaves the account flat | `test_invert_with_unexpected_direction_case_opens_a_buy`, `test_non_invert_forwards_unexpected_direction_to_the_broker_unchanged` |
| A malformed lot (`0.01`, `abc/100`, `0.01/100/2`, `0.01/0`) crashes the handler after reading the balance; a nonsensical lot that parses (`0/100`, `-0.01/100`, `inf/100`, `nan/100`, or a balance too small to round above 0) is sent to the broker as quantity 0, negative, infinite or NaN | `test_malformed_lot_raises_after_reading_balance_before_touching_positions`, `test_nonsensical_lot_that_parses_is_sent_to_the_broker`, `test_nan_lot_is_sent_to_the_broker` |
| A rejected order raises inside the background handler *after* the existing position was closed, leaving the account flat; the `while not order_id` retry loop never runs because the client raises rather than returning an empty id | `test_broker_rejection_propagates_after_existing_position_was_closed` |
| Closing polls in a tight loop with no delay or limit, re-sending a close request on every poll until the broker fills it, while holding the global lock | `test_close_request_is_resent_on_every_poll_until_the_broker_fills_it` |
| The webhook returns 200 before the signal is handled; invalid payloads fail in a background thread and the caller never learns                                      | `test_truncated_payload_raises_index_error` and the other `raises` tests    |
| An invalid `Invert` value is rejected only *after* the existing position is closed                                                                                  | `test_invalid_invert_value_raises_after_existing_position_was_closed`       |
| An unknown action, including case or whitespace variants such as `Open` or ` open`, is silently ignored | `test_unknown_action_neither_closes_nor_orders` |
| The generated webhook path, the only thing protecting the endpoint, comes from `random` instead of a cryptographically secure source                                | `test_generated_webhook_url_has_two_lowercase_alphanumeric_segments`        |
| The account password is passed as a command-line argument, so it shows up in the process list                                                                      | not pinned (startup wiring)                                                 |
| `libs/AsciiAlerts.py` contains an invalid escape sequence (a `SyntaxWarning` today, an error in a future Python)                                                     | not pinned                                                                  |
| Only `tradelocker` is pinned (#23); `pandas`, `fastapi`, `uvicorn` and the rest float, and the Dockerfile runs `apt-get update`, so a rebuilt image can change behaviour with no code change | step 2c: lock file |
| `--port` is documented in the README but never passed by the Docker command                                                                                         | not pinned                                                                  |

## Not covered by tests yet

The webhook route is registered inside `main()`, behind the TradeLocker login
and `uvicorn.run`, so the characterization tests stop at
`handle_position_normal`. Step 5 brings the route under test.
