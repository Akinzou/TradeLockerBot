# ADR 0002: CI quality gates and image publishing

- Status: Accepted
- Date: 2026-11-11

## Context

CI used to run only `compileall`, plus flake8 limited to syntax errors. It had
no tests and no security scanning. The image-publishing workflow ran after
*every* successful CI run, pull requests included, and built whatever `master`
pointed to at that moment rather than the commit that was validated.

## Decision

The `Python (3.11, 3.12) ,` workflow runs these jobs on every pull request and
on every push to `master`:

| Job            | Blocks merge when                                                                                    |
|----------------|------------------------------------------------------------------------------------------------------|
| `tests`        | pytest fails on Python 3.11 or 3.12, or flake8 finds a syntax error or an undefined name             |
| `semgrep`      | Semgrep `p/python`, `p/security-audit`, `p/secrets` or `p/github-actions` reports an `ERROR` finding |
| `docker-build` | the image fails to build                                                                             |
| `ci-ok`        | any job above did not succeed; this is the only status check required by `master` branch protection |

*Update:* since [ADR 0007](0007-locked-runtime-dependencies.md), `tests` also
fails when the dev tools moved a locked package, and `docker-build` fails
when the image's packages differ from the lock. Since
[ADR 0017](0017-override-the-clients-vulnerable-pins.md), `tests` and
`docker-build` also fail when the installed lock does not hold what its
packages need, or an override is not honoured or no longer needed.

Semgrep `WARNING` and `INFO` findings never fail the build. They are written
to the job summary, and each pull request description records the decision
for each one: fixed now, or accepted with a reason.

Semgrep runs in its own job because its pinned dependencies conflict with
`tradelocker`'s (`PyJWT`, `python-dotenv`). Installing both into one
environment silently downgrades or upgrades the bot's runtime libraries.

The publish workflow (`docker-image.yml`) now runs only for successful CI runs
on `master` that were triggered by a push or started manually
(`workflow_dispatch`, used to rebuild the image when `master` has not changed).
It checks out the exact commit that CI validated (`workflow_run.head_sha`).

Workflows are scanned too (`p/github-actions`), because they hold the
publishing credentials. Third-party actions are therefore pinned to full
commit SHAs, with the release tag in a comment: a tag can be repointed by
the action owner, a SHA cannot.

A code-file size budget (300 lines for `.py`, `.sh` and `.ps1`) is enforced by
`tests/test_code_file_size.py`.

## Consequences

- New gates are added as jobs listed in `ci-ok.needs`, so branch protection
  never needs editing.
- `docker-image.yml` matches the CI workflow by its `name:`. Renaming the CI
  workflow requires updating the trigger in the same change.
- The published image is rebuilt from that commit, not promoted from the CI
  build. Since [ADR 0007](0007-locked-runtime-dependencies.md), both builds
  install every Python package from a hashed lock, and the `apt-get` layer is
  gone. The base image tag `python:3.11-slim` still moves until it is pinned
  by digest (roadmap step 2g). Fixing the inputs addresses the cause;
  promoting the CI image would only hide the drift until the next rebuild.
- Semgrep's version is pinned, but its rule packs come live from the Semgrep
  registry. A newly published `ERROR` rule can turn `master` red, and block
  publishing, with no code change. We accept this: a new blocking finding is
  real information about code users run live, and vendoring the rules would
  delay exactly the updates the gate exists for.
- Changes to `docker-image.yml` cannot be exercised by their own pull request,
  because `workflow_run` always uses the copy on `master`. Check the first
  publish run after merging such a change.
