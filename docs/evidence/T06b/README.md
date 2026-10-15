# T06b lineage changelog and centralized logs (2026-10-15)

| Done when | Status | Evidence |
|---|---|---|
| A new edge appears in the changelog | PASS (dev) | baseline, then a new job (`meridian-merchant-export`, reads `gold.merchant_daily`) and the backfill: 4 data-layer edges `added` in `gov.lineage_changelog`; `obs_dev.json`. Prod baseline taken 21:20 SGT; the 02:00 SGT nightly run should flag the same edges |
| The health view answers "what failed in the last 24h and why" in one query | PASS | `SELECT * FROM obs.v_pipeline_health WHERE status IN ('FAILED','ERROR','BREACH','QUARANTINED')`: check breaches with messages, pipeline errors, quarantine counts by rule, failed job and task runs |
| A dated log file exists | PASS | `/Volumes/<catalog>/obs/exports/logs/<date>/`: `pipeline_health.jsonl`, `job_runs.csv`, `pipeline_events.jsonl`, `manifest.json`, in dev and prod |

What is native and what is BUILD:
- Native: the pipeline event log, published as `obs.pipeline_event_log`; expectation metrics in it; system tables
  `system.lakeflow.*`, `system.query.history`, `system.access.audit`, `system.access.table_lineage`.
- BUILD: the views in `sql/obs_views.sql`, the export job, and the snapshot-and-diff changelog.

Exports go to a managed volume on the workspace's own storage. An external volume on an S3 prefix takes the
same code with a different path (not built: no AWS extras in this POC).
