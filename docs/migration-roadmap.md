# Migration roadmap

This is the live state of the migration described in
[ADR 0001](adr/0001-incremental-layered-migration.md). Update it in every
migration pull request.

## Steps

| # | Step                                                                                                             | Kind      | Status |
|---|------------------------------------------------------------------------------------------------------------------|-----------|--------|
| 1 | Characterization tests, CI gates, publish only from `master`                                                     | safety    | done   |
| 1a | Restore image publishing with the workflow token and report publish failures ([ADR 0003](adr/0003-publish-with-workflow-token.md))       | safety    | blocked: owner grants package access |
| 1b | Delete the `PERSONAL_ACCESS_TOKEN` secret after the first successful publish                                       | safety    | todo   |
| 2 | Domain: trading signal parsed from the webhook payload, lot sizing, direction inversion as pure, tested code     | structure | next   |
| 3 | Layer dependency check (import contract) once the domain package exists                                          | safety    | todo   |
| 4 | Application: execute-signal use case behind a broker port; TradeLocker adapter implements the port              | structure | todo   |
| 5 | Inbound HTTP adapter and composition root; `main_without_ssl.py` becomes a thin entrypoint                       | structure | todo   |
| 6 | Behaviour changes from the list below, one pull request and one ADR each                                         | behaviour | todo   |

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

## Known defects (fix in step 6, not during restructuring)

| Defect                                                                                                                                                              | Pinned by                                                                   |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| A rejected order raises inside the background handler *after* the existing position was closed, leaving the account flat; the `while not order_id` retry loop never runs because the client raises rather than returning an empty id | `test_broker_rejection_propagates_after_existing_position_was_closed` |
| Closing polls in a tight loop with no delay or limit, re-sending a close request on every poll until the broker fills it, while holding the global lock | `test_close_request_is_resent_on_every_poll_until_the_broker_fills_it` |
| The webhook returns 200 before the signal is handled; invalid payloads fail in a background thread and the caller never learns                                      | `test_truncated_payload_raises_index_error` and the other `raises` tests    |
| An invalid `Invert` value is rejected only *after* the existing position is closed                                                                                  | `test_invalid_invert_value_raises_after_existing_position_was_closed`       |
| An unknown action (neither `open` nor `close`) is silently ignored                                                                                                  | `test_unknown_action_neither_closes_nor_orders`                             |
| The generated webhook path, the only thing protecting the endpoint, comes from `random` instead of a cryptographically secure source                                | `test_generated_webhook_url_has_two_lowercase_alphanumeric_segments`        |
| The account password is passed as a command-line argument, so it shows up in the process list                                                                      | not pinned (startup wiring)                                                 |
| `libs/AsciiAlerts.py` contains an invalid escape sequence (a `SyntaxWarning` today, an error in a future Python)                                                     | not pinned                                                                  |
| Runtime dependencies in `requirements.txt` are unpinned and the Dockerfile runs `apt-get update`, so a rebuilt image can change behaviour with no code change                                                | not pinned                                                                  |
| `--port` is documented in the README but never passed by the Docker command                                                                                         | not pinned                                                                  |

## Not covered by tests yet

The webhook route is registered inside `main()`, behind the TradeLocker login
and `uvicorn.run`, so the characterization tests stop at
`handle_position_normal`. Step 5 brings the route under test.
