# T06 orchestration, triggers, lineage and recovery (2026-10-15)

| Done when | Status | Evidence |
|---|---|---|
| File-arrival trigger fires with a run ID | PASS | prod ingest run `712046480190183`, trigger `FILE_ARRIVAL`, SUCCESS (pipeline, then quality checks) after the incident, bad-row and drift batches landed; `triggers_prod.json` |
| Table-update trigger fires | PASS | prod `meridian-acquirer-status` run `105430370750112`, trigger `TABLE`, about 110 s after the backfill wrote `silver.payments`; it fired again after each later pipeline write |
| Cron trigger fires | PASS | generated ingest jobs, trigger `PERIODIC` (for example `meridian-ingest-fx-rates` hourly); the 08:00 SGT digest is also on cron |
| Forced failure takes the `AT_LEAST_ONE_FAILED` path and notifies | PASS | dev run `639453994800970`: three checks failed once each (serverless auto-optimization off), `escalate` ran and listed 5 distinct breaches; each failed check carries a task-level failure email. Slack delivery waits for the bot token |
| Duration warning rule | PASS (configured) | `RUN_DURATION_SECONDS > var.duration_warning_seconds` (900 s; 120 s in dev so dev runs exercise it) with `on_duration_warning_threshold_exceeded` |
| Generated cross-job graph | PASS | `docs/job_graph.md` from `scripts/job_graph.py` (BUILD) |
| Root cause names the bad job and run in under 2 minutes | PASS | `DESCRIBE HISTORY silver.payments` is immediate: `MERGE` (or `UPDATE`) by `meridian-backfill-fx-correction`, job run ID, rows changed, predicate; `drill_dev.json`, `drill_prod_update.json`. Lineage lists the run through its read of `silver.payments` (see limits) |
| Table restored | PASS | `gold.acquirer_status` restored by the `meridian-restore-table` job in prod (version 2 to 0) and by SQL in dev (11 s); `silver.payments` recomputed from bronze by a selective full refresh (1 to 2 min); prod scores 16/16 afterwards (`T03/score_prod.json`) |

Runbook: `docs/runbooks/bad_backfill.md`.

Limits found (also in `spikes.md`):
- `RESTORE` is not supported on pipeline streaming tables; silver recovers by selective full refresh from bronze.
- DML into a pipeline streaming table from a job (`UPDATE` or `MERGE`) leaves no lineage write edge; table history records it.
- `DESCRIBE HISTORY` reports `triggerType: manual` for table-triggered runs; the Jobs API run says `TABLE`.
- Lineage is a system table with a lag (7 to 30 min here), so the drill's bad write runs hours before it is shown.

Prod MERGE drill, PASS (`drill_prod.json`): the backfill ran 2026-10-15 21:50 SGT (run `327365315463957`) and
multiplied 12 Oct by 100 (128,291.27 to 12,829,127.00); history named the job and run immediately; by morning lineage
showed that run reading `silver.payments` into a new `bronze.fx_corrections`, and the 02:00 lineage changelog had flagged
both edges. Recovered 2026-10-16 10:05 SGT: `meridian-restore-table` put `gold.acquirer_status` back to version 4, a
selective full refresh recomputed silver (1.5 min), and prod scores 16/16.
