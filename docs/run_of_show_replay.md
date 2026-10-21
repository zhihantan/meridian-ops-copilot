# Run of show, replay (45 minutes, nothing to run)

This version walks through the incident that already happened in prod on 15 and 16 Oct, instead of triggering one
live. Every scene points at a run, a table version or a dashboard page that is already in the workspace, so no job,
pipeline or deployment needs to run before or during the demo. Prod's schedules keep running on their own and do not
change anything shown here. The live version, which resets and stages prod first, is `run_of_show.md`.

**Do not reset or stage prod.** The reset clears the incident, the workflow runs and the history this replay shows.

Say at the start: the payment data is synthetic and stops at 15 Oct 13:00 SGT. Genie and the copilot read "now" and
"the last 24 hours" relative to the data's last hour (`config/genie_space.yaml`, `agent.compute_impact`).

## Before the demo

- VPN on: the workspace has an IP access list.
- Open the tabs: the jobs `meridian-ingest` and `meridian-recover` (prod) and `meridian-integration-test` (staging),
  the prod pipeline `meridian-dlc`, the "Meridian ops" dashboard, the SQL editor with the queries below, and a
  terminal for the persona questions (`scripts/ask.py`, in `run_of_show.md`).
- Screen sharing: the workspace also holds other projects. Open Meridian items from direct links, or from lists
  filtered on "meridian", never from unfiltered lists.

## Scenes

Times are Singapore time. The SQL editor shows UTC, 8 hours earlier, unless the query converts it.

| # | Minutes | Scene | Show (already in the workspace) | Optional live steps (no jobs) |
|---|---|---|---|---|
| 0 | 5 | Security architecture | Slides | |
| 1 | 6 | Detect | 1. `meridian-ingest` run 712046480190183 (15 Oct 20:55, trigger "File arrival"): the incident file started the run, and the pipeline update it ran wrote 2,220 rows to `silver.payments` (version 5) and quarantined 85. 2. Run 971387763229970 (18 Oct), the job as it is now: the pipeline, three checks, escalation and the AI digest in one run. Drift flags acq_7, freshness flags that no payments arrived after 15 Oct, and PII coverage flags the untagged `secondary_email`. Open the escalate task's output: the 5 issues it would post to Slack. 3. The AI digest of the quarantine, rule by rule, in `obs.dq_digest` (query below): counts from SQL; summary, likely cause and fix written by the named model, flagged AI-generated and not reviewed. 4. Dashboard, Pipeline health page: the Acquirer status table (degraded first) shows acq_7 degraded, 16.2% failures against a 1.9% baseline; below it, the issues of the last 14 days: the 18 Oct check failures and breaches, and the quarantine by rule | |
| 2 | 4 | Protect | `docs/evidence/T04/persona_probe_prod.json` (20 Oct): Ava gets masked contacts and her home market only; Ben gets every market, still masked; Eli gets raw values. The Payments by market chart on the dashboard's Pipeline health page, which each viewer queries as themselves | `uv run --group dbx python scripts/probe_personas.py --target prod` (read-only, about 10 s) |
| 3 | 5 | Root cause | Table history (queries below). In `silver.payments`, version 12 is a MERGE by `meridian-backfill-fx-correction` at 15 Oct 21:49 (job run 327365315463957), changing 2,311 rows. In `gold.acquirer_status`, version 5 was rebuilt from those rows by the table-update trigger, and version 6 is the RESTORE at 16 Oct 09:59 (`meridian-recover` job run 200160456197525). Silver version 13 is the repair refresh from bronze at 10:00, and gold version 7 was rebuilt from the repaired silver at 10:05. Then the recovery steps in `docs/runbooks/bad_backfill.md` | Run the queries |
| 4 | 8 | Ship a fix | GitHub: the branch `demo/weaken-amount-rule`. Staging's `meridian-integration-test` history: run 949539290745936 FAILED on that branch (17 Oct 19:10; 12 of 16, because nine negative amounts reached silver), then 896604315791882 passed on `main` (19:19). Run 181603199797724 (20 Oct) passed all 10 tasks of today's job. The release record: `SELECT * FROM meridian.obs.releases` shows `deploy main 4298b30` by Eli, written by `meridian-post-deploy` run 62476880595203 | |
| 5 | 8 | The copilot works the incident | The 17 Oct runs in `meridian.agent.runs` and the dashboard's Copilot page. Ben's runs went from s1 to s6 with an approval. Ava's stopped at s2, because the SLA clause is finance-only. Some runs still wait on approvals. `docs/evidence/T18/` has the drills | Ask live as Ben: "acq_7 is degraded. Run RB-014 for acq_7 over the last 24 hours". It works on this data: each run computes its own impact and batch, and asks for approval above SGD 500. The full flow, with Eli's approval, is scene 5 of `run_of_show.md` |
| 6 | 5 | Claude Code over MCP; memory | `docs/evidence/T23/`: the same prompts as Ava, Ben and Gus give different results, with a row per user in the audit log and gateway usage. `docs/evidence/T25/`: 5 memory probes, no leaks | Claude Code as each persona |
| 7 | 4 | Trust and cost | The dashboard's Copilot page: runs by caller, slowest tools, refusals and denials. The prompt-cache result (`docs/evidence/T27/`: 80.5% cheaper at list price). Then the Data products page (what was built, its quality, protection, lineage and readers) and the Jobs and pipeline page (triggers, reliability, rows written, expectations and serverless cost by job), the daily audit export, and the gaps slide | |

## Queries

```sql
-- Scene 1: the AI digest of the quarantine, rule by rule
SELECT from_utc_timestamp(generated_at, 'Asia/Singapore') AS generated_sgt, dataset, rule, `rows`, summary, likely_cause,
       suggested_fix, model, ai_generated, human_reviewed
FROM meridian.obs.dq_digest WHERE digest_date = (SELECT max(digest_date) FROM meridian.obs.dq_digest) ORDER BY `rows` DESC;

-- Scene 3: who wrote silver.payments, and gold's history
SELECT version, from_utc_timestamp(timestamp, 'Asia/Singapore') AS at_sgt, operation, job.jobName, job.runId,
       coalesce(operationMetrics['numTargetRowsUpdated'], operationMetrics['numUpdatedRows']) AS rows_changed
FROM (DESCRIBE HISTORY meridian.silver.payments)
WHERE operation NOT IN ('STREAMING UPDATE', 'SET TBLPROPERTIES', 'DLT SETUP')
ORDER BY version DESC;

SELECT version, from_utc_timestamp(timestamp, 'Asia/Singapore') AS at_sgt, operation, job.jobName, job.runId
FROM (DESCRIBE HISTORY meridian.gold.acquirer_status) ORDER BY version DESC;

-- Which jobs and pipelines read or wrote silver.payments during the incident (15 and 16 Oct)
WITH jobs AS (SELECT job_id, name FROM system.lakeflow.jobs
              QUALIFY row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) = 1),
     pipes AS (SELECT pipeline_id, name FROM system.lakeflow.pipelines
               QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1)
SELECT max(from_utc_timestamp(l.event_time, 'Asia/Singapore')) AS last_seen_sgt, coalesce(j.name, p.name) AS job_or_pipeline,
       IF(l.target_table_full_name = 'meridian.silver.payments', 'writes', 'reads') AS direction,
       IF(l.target_table_full_name = 'meridian.silver.payments', l.source_table_full_name,
          l.target_table_full_name) AS other_table
FROM system.access.table_lineage l
LEFT JOIN jobs j ON l.entity_type = 'JOB' AND l.entity_id = j.job_id
LEFT JOIN pipes p ON l.entity_type = 'PIPELINE' AND l.entity_id = p.pipeline_id
WHERE (l.target_table_full_name = 'meridian.silver.payments' OR l.source_table_full_name = 'meridian.silver.payments')
  AND l.event_date BETWEEN '2026-10-15' AND '2026-10-16' AND l.entity_type IN ('JOB', 'PIPELINE')
GROUP BY ALL ORDER BY last_seen_sgt DESC;
```

A table's history records the task run ID (`job.runId`), not the job run ID that the Jobs UI lists: the backfill's
task run is 905857144361393, and the restore's is 1099635984702077.

## What a replay cannot show

- **No live event.** The file-arrival trigger is shown by the run it started, not fired in front of the customer.
- **The dashboard's issues table covers 14 days,** so the incident's breaches and quarantine stay on it until
  about 29 Oct.
- **No bundle UI.** No Git folder has been created yet, so scene 4 shows GitHub and the run history. Creating a Git
  folder in the UI takes about 2 minutes and adds it.
- **Old data.** The data stops on 15 Oct, and the freshness check says so.

## Questions to expect

- **"Why did `meridian-ingest` fail on 15 Oct at 18:14?"** On the first day, the release principal could not yet
  run the pipeline. It was granted, and the run at 18:38 succeeded.
- **"Why does gold's history say `meridian-restore-table`?"** The job was renamed `meridian-recover` when the jobs
  were consolidated on 17 Oct. A table's history keeps the job name from the time of the write.
