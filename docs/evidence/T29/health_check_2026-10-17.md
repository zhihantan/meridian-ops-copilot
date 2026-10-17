# Asset health check and clean-up (2026-10-17 evening), PASS

Every Meridian asset was listed in dev, staging and prod and checked. Assets with no use in a target were removed.

## Checked

| Asset | Result |
|---|---|
| Jobs | Latest run SUCCESS for every job that has run, except `meridian-quality-checks`, which ends SUCCESS_WITH_FAILURES by design: a check that finds a breach fails its task and emails. The breaches are drift from the planted incident, stale data, and the planted untagged `secondary_email` column; none are errors |
| Pipelines | `meridian-dlc`, `[staging] meridian-dlc` and `[dev <user>] meridian-dlc`: latest update COMPLETED in all three |
| Staging integration test | Latest run PASS (16/16, `T09/integration_pass.json`) |
| Copilot app | ACTIVE. One question as Ben, answered in 38 s: the degraded acquirer from Genie (cited) and the finance SLA clause from the knowledge base |
| Dashboards | Every dataset query of the dev and prod "Meridian ops" dashboards returns rows; staging was checked earlier the same day |
| AI Search | Endpoint online. The general and finance indexes in dev and prod are ready (33 and 2 documents) |
| Other | Quality monitors active on dev and prod `silver.payments`; Genie spaces for dev and prod; memory stores `mem-general` and `mem-finance` |

## Removed

| What | Why |
|---|---|
| 19 jobs from staging (kb, demo reset, workflow setup, exports other than logs, ingest jobs, backfill and recovery drills, digest, secret probe) | Staging only runs the integration test and what its dashboard reads. Those jobs are now defined for dev and prod only (`targets:` in each resource file); dev's and prod's resolved jobs were compared before and after and are unchanged |
| `meridian-secret-probe` from prod | The T08 probe secret exists only in `meridian_dev.secrets`, so the prod job could only fail. It stays in dev |
| MLflow experiments `/Shared/agentbricks_traces/meridian-copilot` and `meridian-parity` | The copilot traces to the Unity Catalog-linked `meridian-copilot-uc` since 2026-10-16; parity belonged to the removed local development. Both deleted (soft delete, restorable for 30 days) |
| `_parity` and `_parse_test` folders in the dev exports volume | Scratch files from the removed parity check and a one-off parsing test |

Jobs per target after clean-up: dev 23, prod 22, staging 5 (was 23, 23 and 24).

## Consolidation (later the same evening): 50 jobs to 21

The jobs were merged so that each job is one thing an operator would run or watch. Dev and prod have 10 each,
staging 1. Evidence written before this names the jobs as they were then; this is the mapping.

| Now | Was |
|---|---|
| `meridian-ingest` (file arrival): pipeline, quality checks, escalation, AI digest | `meridian-ingest`, `meridian-quality-checks`, `meridian-dq-digest` |
| `meridian-daily` (00:30 SGT): views, log and audit exports, lineage changelog, finance export | `meridian-export-logs`, `meridian-export-audit`, `meridian-lineage-changelog`, `meridian-merchant-export` |
| `meridian-ingest-sources` (hourly, generated): one task per source in `config/sources.yaml` | five generated `meridian-ingest-<source>` jobs |
| `meridian-post-deploy` (after each deploy): governed procedures, `kb.workflows` seed, release record | `meridian-workflow-setup`, `meridian-release-log` |
| `meridian-recover` (manual, action `restore` or `reprocess`) | `meridian-restore-table`, `meridian-reprocess-quarantine` |
| `meridian-integration-test` (staging only): also refreshes gold, checks and views for staging's dashboard | `meridian-integration-test`, and staging's copies of the gold refresh, quality checks, views and release log |
| unchanged | `meridian-acquirer-status`, `meridian-kb-sync`, `meridian-kb-sweep`, `meridian-backfill-fx-correction`, `meridian-demo-reset` |
| removed after their measurements | `meridian-kb-freshness-probe` (T14), `meridian-secret-probe` (T08) |

Merged jobs keep the original job's definition, so their run history continues (the ingest, export-logs, workflow
setup and restore jobs). The container image Dockerfile (`app_layer/`) was removed with its build workflow.
