# T09 multi-developer CI/CD, GitOps and rollback (2026-10-15)

| Done when | Status | Evidence |
|---|---|---|
| Workflows exist: PR checks and integration, staging on merge, prod on tag with approval, rollback, image | PASS | `.github/workflows/{pr,deploy,rollback,image}.yml`, `docs/cicd.md` |
| Staging deploys and runs the integration test | PASS | `scripts/ci_integration.sh staging` against the deployed staging target: fresh data, baseline first, full refresh, then incident, bad rows and drift; 16/16 (`T03/score_staging.json`), 7.5 min end to end. Run from a laptop until GitHub has the CI credential |
| Both developers' branches deploy without interference | OPEN | development mode prefixes per user; PR flow runs once GitHub is set up |
| Staging blocks a rule-weakening PR | OPEN | the `integration` job fails `score_pipeline.py`; PR flow runs once GitHub is set up |
| Prod needs approval | OPEN | `prod` environment reviewer, set by `scripts/setup_github.sh` |
| Rollback under 10 minutes, workflow run URLs saved | OPEN | `rollback.yml`; drill once GitHub is set up |

Setup blocker: GitHub needs the CI principal's OAuth secret in its environments, which `scripts/setup_github.sh`
creates and stores without printing it. A repo admin runs it once.

Design notes:
- Pull requests deploy an ephemeral `ci` target (staging catalog, `[ci]` names, `ci_` schemas) and destroy it afterwards.
- Staging and prod share one workspace; pipeline names must be unique, so staging's pipeline is `[staging] meridian-dlc`.
- Staging and ci pause triggers and swap the table-update trigger for a paused schedule: a fresh deployment has no
  `silver.payments` to watch, and CI drives every run there.
