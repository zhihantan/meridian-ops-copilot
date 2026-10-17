# Promotion from dev to prod, inside the workspace (T09)

GitHub holds the code, assets and bundle. Every deployment happens inside the workspace, from a Git folder, with
the bundle UI. The workspace's IP access list blocks GitHub's hosted runners (observed 2026-10-17), so no
deployment runs from GitHub.

| Step | Who | Where | What |
|---|---|---|---|
| Develop | Fay | her Git folder, `dev` target | deploy her own prefixed copy, run it, commit, push, open a pull request |
| Review | Eli | GitHub | read the pull request |
| Integration test | Eli | a Git folder on the branch, `staging` target | deploy to staging, then run `meridian-integration-test` (below). Any miss fails the run |
| Merge | Eli | GitHub | merge only if the integration run passed |
| Release | Eli | a Git folder on `main`, `prod` target | deploy prod, tag the commit, then run `meridian-post-deploy` (kind `deploy`): it applies the governed procedures and records the release |
| Roll back | Eli | the same Git folder, checked out at the previous tag | deploy prod again, run `meridian-post-deploy` (kind `rollback`), then `meridian-recover` (action `reprocess`) |

`meridian-integration-test` (BUILD, `resources/jobs_integration.yml`) works in five steps:
1. It generates fresh synthetic data and lands the baseline.
2. It runs a full refresh of the pipeline.
3. It lands the incident batches.
4. It runs a pipeline update.
5. It scores every planted defect against `planted.json`.

## Gates that matter

- **The integration test is the contract.** A change that lets a planted bad row into silver, or quarantines a
  good one, fails `meridian-integration-test`, so it is not promoted. The checks are in
  `src/meridian/common/score.py`, the same ones `scripts/score_pipeline.py` runs.
- **Rule changes travel with their test data.** A rule change that is meant to change outcomes updates
  `config/scenario.yaml` and the generator in the same pull request, so `planted.json` describes the new expected
  behavior.
- **Prod is admin-only.** Only meridian-admin deploys staging and prod. Both run as the release principal
  `meridian-ci`, so developers never hold write access to prod data.
- **The integration job exists only in staging.** It rewrites the landing folders and the pipeline's tables, and
  it refuses to run on any other target.

## Limits to state plainly

- **No automatic merge-to-deploy.** Promotion is a deliberate act by an admin, recorded in `obs.releases` by
  `meridian-post-deploy`. A CI service could run the same steps only from a runner that can reach the workspace:
  inside its network, or from an allowed address.
- **Rollback is redeploying a known-good tag.** It is not a button.
- **Code rollback does not roll back data.**
  - Rows quarantined by a bad rule stay quarantined until `meridian-recover` (action `reprocess`) runs them
    through the restored rules.
  - Tables written wrongly need a refresh from bronze (pipeline tables) or `RESTORE` (ordinary tables), as in
    `docs/runbooks/bad_backfill.md`.
- **Removing a resource from the bundle destroys it on the next deploy.** A deleted pipeline keeps its tables by
  default since 2026-09-25, but they stay frozen (no updates) until a pipeline adopts them; the API's
  `cascade=true` deletes them.
- **One person plays both roles in this POC.** Fay and Eli are the same presenter, so the separation of duties is
  shown through group permissions (meridian-de versus meridian-admin), not by two people.
