# ADR 0003: Publish the image with the workflow token

- Status: Accepted
- Date: 2026-11-11

## Context

`docker-image.yml` logged in to GHCR with a personal access token stored as
the `PERSONAL_ACCESS_TOKEN` secret. GHCR rejects that token
(`denied: denied`), and every publish run has failed since. Whether the token
expired, was revoked or lost its scope was not confirmed. The `latest` image
users pull was built on 2025-06-28. No application code has changed since
then, so users are not running stale bot logic yet. But no future change would
have reached them, and the only sign of the failure was a red run that nobody
watched.

## Decision

1. Publish with the workflow's own `GITHUB_TOKEN`. Only the publishing job is
   granted `packages: write`.
2. Label the image at build time with `org.opencontainers.image.source`
   (derived from the building repository) and `org.opencontainers.image.revision`.
   The source label links the GHCR package to the repository.
3. A failed publish opens one tracking issue, *Docker image publishing is
   failing*, or comments on it if it is already open, so the failure reaches
   repository watchers instead of staying hidden in the Actions tab.

## Consequences

- The token exists only for one job run: nothing can expire between runs and
  there is no long-lived credential to leak.
- **Owner action required, ideally before merging:** the existing package was created with the
  personal token and is not linked to the repository, so the label alone cannot
  authorise the first push. Grant access in *Package settings → Manage Actions
  access → add `TradeLockerBot` with the Write role*.
- If the grant comes after the merge, the merge's publish run fails and opens
  the tracking issue. Re-run it after granting access:
  `gh workflow run python-package.yml --ref master` (publishing follows a green
  CI run).
- After the first successful publish, delete the `PERSONAL_ACCESS_TOKEN`
  secret (tracked in the migration roadmap). Until then, the decision's
  "no long-lived credential" benefit is not realised.

## Alternatives considered

- **Renew the personal access token.** Rejected: it fixes today's symptom
  and recreates the cause, a long-lived secret that fails silently.
- **Check image freshness on a schedule** instead of reporting failures.
  Deferred: reporting the failure at its source is enough for now and needs
  no extra workflow.
