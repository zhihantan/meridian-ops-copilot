# T09 promotion from dev to prod, inside the workspace (2026-10-15, reworked 2026-10-17), PARTIAL

GitHub holds the code, assets and bundle. Every deployment happens inside the workspace, from a Git folder with the
bundle UI (`docs/cicd.md`). The workspace's IP access list blocks GitHub's hosted runners. The first GitHub deploy
was refused before it could sign in, so the GitHub workflows were removed on 2026-10-17.

| Done when | Status | Evidence |
|---|---|---|
| The integration test runs inside the workspace | PASS | `integration_pass.json`: `meridian-integration-test` on staging from `main` (41b8819), 16 of 16 planted defects handled as the contracts say, 6.1 minutes (the first run, before that commit, took 6.5) |
| Staging blocks a rule-weakening change | PASS | `integration_weakened.json`: the same job on the branch `demo/weaken-amount-rule` (`amount_positive` from quarantine to warn) failed at the score step, 12 of 16. Nine planted negative amounts reached silver, so the quarantine and silver checks failed |
| Only admins deploy staging and prod | PASS | `T07/prod_root_acl.json`: only admins and the release principal can write the deployment folders; developers can read |
| A prod release from a Git folder, logged | OPEN | Rehearsal step: Eli deploys `main` to prod from the bundle UI, then runs `meridian-release-log` |
| A rollback in under 10 minutes | OPEN | Rehearsal step: deploy the previous tag from the Git folder, timed |

The job (BUILD, `resources/jobs_integration.yml`, `src/meridian/jobs/integration.py`) runs these tasks:
1. It generates fresh synthetic data with the repo's generator, into the run's folder on the exports volume.
2. It clears the landing folders and lands the baseline.
3. It runs a full refresh.
4. It lands the incident, bad-row and drift batches.
5. It runs an update.
6. It scores with `src/meridian/common/score.py`, the same checks as `scripts/score_pipeline.py`.

It exists only in staging, and it refuses to run on any other target. Staging deploys five jobs: the integration test and what its dashboard reads (quality
checks, gold refresh, observability views) plus the release log. All other jobs are dev and prod only.

Removed on 2026-10-17:
- **GitHub workflows:** pull request checks, ephemeral `ci` deployments, staging and prod deploys, rollback and the
  image build.
- **The GitHub CI setup script.**
- **The per-PR `ci` target.**

The CI token those workflows would have used is listed for revocation in the session report.

Design notes:
- **Shared workspace.** Staging and prod share one workspace, and pipeline names must be unique, so staging's
  pipeline is `[staging] meridian-dlc`.
- **Paused triggers in staging.** Staging pauses triggers and swaps the table-update trigger for a paused schedule:
  a fresh deployment has no `silver.payments` to watch, and the integration job drives every run there.
