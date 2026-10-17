# T07 self-service development in the workspace (2026-10-17), PARTIAL

Development happens inside the workspace only. A developer works in a Git folder and deploys their own copy of
the bundle from the bundle UI (`docs/onboarding.md`). Nothing is installed on a laptop, and no data leaves the
workspace. This replaces the earlier laptop and Codespace setup over Databricks Connect, which was removed on
2026-10-17, so all development uses one path.

| Done when | Status | Evidence |
|---|---|---|
| Each developer gets an isolated copy | PASS | Development mode prefixes every schema, job and pipeline with the deploying user (`dev_<user>_`) and pauses schedules. The dev deployments behind T03 to T27 ran this way |
| Code runs on serverless, as the developer | PASS | Jobs and the pipeline run on serverless; bundles in the workspace need serverless and run as the current user (`docs/evidence/spikes.md`, 2026-10-17) |
| No data on a laptop | PASS | `tests/test_no_data_in_repo.py` |
| First deployment from a Git folder, timed | OPEN | A UI step for the rehearsal (`manual_steps.md`): link GitHub, create the Git folder, deploy `dev` from the bundle UI. Record the minutes from the Git folder to a deployed dev target here |
| Developers cannot deploy staging or prod | PASS | `prod_root_acl.json`: the prod deployment folder gives CAN_MANAGE only to admins and the release principal |

The second developer persona (Gus) was dropped on 2026-10-17. He is a service principal and cannot sign in to the
workspace UI. Gus remains a persona for Claude Code over MCP (T23).
