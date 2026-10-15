# CI/CD, GitOps and rollback (T09)

| Event | Workflow | What runs | Identity |
|---|---|---|---|
| Pull request to `main` | `pr.yml` `checks` | lockfiles current (`uv lock --check`), hash-checked install, ruff, pytest, gitleaks secret scan | GitHub runner |
| Pull request to `main` | `pr.yml` `integration` | deploy an ephemeral `ci` target (staging catalog, `ci` schemas), land fresh synthetic data in the demo order, run the pipeline, `score_pipeline.py` against `planted.json`, destroy | `meridian-ci` (OAuth M2M) |
| Merge to `main` | `deploy.yml` `staging` | deploy `staging`, the same integration test, log to `obs.releases` | `meridian-ci` |
| Tag `v*` | `deploy.yml` `prod` | waits for the `prod` environment reviewer, deploys `prod`, release notes from commits, log to `obs.releases` | `meridian-ci` |
| Manual, input a tag | `rollback.yml` | checkout the tag, deploy `prod`, reprocess quarantined rows with the restored rules, log the rollback | `meridian-ci` |
| Tag `v*` or manual | `image.yml` | build `app_layer/Dockerfile`, push to GHCR tagged with the git SHA and semver | `GITHUB_TOKEN` |

Developers deploy their own `dev` target from their machines (development mode prefixes every resource
with the user, so parallel branches never touch each other's schemas or jobs).

## Setup (once)

`scripts/setup_github.sh`, run by a repo admin: GitHub environments `ci`, `staging`, `prod` with the CI
principal's host, client ID and a 90-day OAuth secret; a required reviewer on `prod`; branch protection on
`main` requiring the `checks` and `integration` jobs.

Why OAuth M2M and not GitHub OIDC: a Databricks federation policy for GitHub OIDC is an account-level
setting, and this workspace has no account admin. With one, set `DATABRICKS_AUTH_TYPE=github-oidc` and drop
the secret.

## Gates that matter

- The integration test is the contract: a change that lets a planted bad row into silver, or quarantines a
  good one, fails `score_pipeline.py`, so the pull request cannot merge.
- A rule change that is meant to change outcomes updates `config/scenario.yaml` and the generator in the same
  pull request, so `planted.json` describes the new expected behavior.

## Limits to state plainly

- Rollback is redeploying a known-good tag; it is not a button.
- Code rollback does not roll back data. Rows quarantined by a bad rule stay quarantined until the
  reprocess step runs them through the restored rules; tables written wrongly need a refresh from bronze
  (pipeline tables) or `RESTORE` (ordinary tables), as in `docs/runbooks/bad_backfill.md`.
- Removing a resource from the bundle destroys it on the next deploy. A deleted pipeline keeps its tables by
  default since 2026-09-25, but they stay frozen (no updates) until a pipeline adopts them; the API's
  `cascade=true` deletes them.
- One GitHub account in this POC: CODEOWNERS is listed, not enforced, and the `prod` reviewer can approve their
  own deployment. With a team, require code-owner review and prevent self-review.
