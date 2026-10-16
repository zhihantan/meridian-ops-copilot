# T06b lineage changelog and centralized logs (2026-10-15)

| Done when | Status | Evidence |
|---|---|---|
| A new edge appears in the changelog | PASS | dev (`obs_dev.json`) and prod (`obs_prod.json`): after the baseline, the nightly run flagged the new finance export reading `gold.merchant_daily` and the backfill writing `bronze.fx_corrections` from `silver.payments`. Prod's 02:00 run predates the data-layer filter, so it also listed the observability jobs' own edges |
| The health view answers "what failed in the last 24h and why" in one query | PASS | `SELECT * FROM obs.v_pipeline_health WHERE status IN ('FAILED','ERROR','BREACH','QUARANTINED')`: check breaches with messages, pipeline errors, quarantine counts by rule, failed job and task runs |
| A dated log file exists | PASS | `/Volumes/<catalog>/obs/exports/logs/<UTC date>/`: `pipeline_health.jsonl`, `job_runs.csv`, `pipeline_events.jsonl`, `manifest.json`, in dev and prod (prod also from the 00:30 SGT scheduled run) |

What is native and what is BUILD:
- Native: the pipeline event log, published as `obs.pipeline_event_log`; expectation metrics in it; system tables
  `system.lakeflow.*`, `system.query.history`, `system.access.audit`, `system.access.table_lineage`.
- BUILD: the views in `sql/obs_views.sql`, the export job, and the snapshot-and-diff changelog.

Exports go to a managed volume on the workspace's own storage. An external volume on an S3 prefix takes the
same code with a different path (not built: no AWS extras in this POC).
