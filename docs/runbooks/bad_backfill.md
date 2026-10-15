# Runbook: a bad write to `silver.payments` (T06)

The drill: `meridian-backfill-fx-correction` (the `bad_backfill_job` resource) loads FX correction factors
into `bronze.fx_corrections` with a units bug (100 instead of 1) and MERGEs one Singapore-time day of
`silver.payments.amount` through them. Its write fires the table-update trigger of
`meridian-acquirer-status`, which rebuilds `gold.acquirer_status` from the bad data.
Evidence: `scripts/backfill_drill.py` (read-only) writes `docs/evidence/T06/drill_<target>.json`.

Replace `meridian` with the target's catalog (and the `dev_<user>_` schema prefix in development mode).

## 1. Detect

`gold.acquirer_status.baseline_daily_amount` jumps for every acquirer (in the dev drill, acq_1 went from
16,790 to 143,537), and `gold.merchant_daily` shows one day at 100 times its volume.

## 2. Diagnose (under 2 minutes)

The table's own history is immediate and names the job and run:

```sql
SELECT version, timestamp, userName, operation, job.jobName, job.jobId, job.jobRunId,
       coalesce(operationMetrics['numTargetRowsUpdated'], operationMetrics['numUpdatedRows']) AS rows_changed
FROM (DESCRIBE HISTORY meridian.silver.payments)
WHERE operation NOT IN ('STREAMING UPDATE', 'SET TBLPROPERTIES', 'DLT SETUP')
ORDER BY version DESC;
```

Lineage answers "which jobs and pipelines operated on `silver.payments` this week?", reads and writes,
across runs. It shows the backfill run reading `silver.payments` and writing a table nobody expected,
`bronze.fx_corrections`. Two limits, observed 15 Oct: lineage is a system table and lags (7 to 30
minutes here), so the bad write must happen well before it is shown; and DML into a pipeline streaming
table from a job (this MERGE, or an UPDATE) is not recorded as a lineage write edge. The table history
above is the record of writes.

```sql
WITH jobs AS (SELECT job_id, name FROM system.lakeflow.jobs
              QUALIFY row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) = 1),
     pipes AS (SELECT pipeline_id, name FROM system.lakeflow.pipelines
               QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1)
SELECT max(l.event_time) AS last_seen,
       IF(l.target_table_full_name = 'meridian.silver.payments', 'writes', 'reads') AS direction,
       l.entity_type, coalesce(j.name, p.name) AS job_or_pipeline, l.entity_id, l.entity_run_id,
       IF(l.target_table_full_name = 'meridian.silver.payments', l.source_table_full_name,
          l.target_table_full_name) AS other_table
FROM system.access.table_lineage l
LEFT JOIN jobs j ON l.entity_type = 'JOB' AND l.entity_id = j.job_id
LEFT JOIN pipes p ON l.entity_type = 'PIPELINE' AND l.entity_id = p.pipeline_id
WHERE (l.target_table_full_name = 'meridian.silver.payments' OR l.source_table_full_name = 'meridian.silver.payments')
  AND l.event_date >= current_date() - INTERVAL 7 DAYS AND l.entity_type IN ('JOB', 'PIPELINE')
GROUP BY ALL ORDER BY last_seen DESC;
```

The nightly lineage changelog (`gov.lineage_changelog`, T06b) flags the backfill's edges as new the next
morning.

Blast radius, by time travel to the version before the bad write (version `N`):

```sql
SELECT to_date(from_utc_timestamp(created_at, 'Asia/Singapore')) AS day,
       sum(amount) AS amount_before
FROM meridian.silver.payments VERSION AS OF <N - 1> GROUP BY 1
ORDER BY 1;
```

## 3. Mitigate: restore the serving table (seconds)

`gold.acquirer_status` is an ordinary Delta table, so `RESTORE` works. In prod it runs as the reviewed
`meridian-restore-table` job, as the deploying service principal, so no person holds standing MODIFY on
prod tables; the job refuses pipeline tables and writes `obs.recovery_audit`:

```sql
DESCRIBE HISTORY meridian.gold.acquirer_status;      -- last version built before the bad write
```

```bash
databricks bundle run -t prod restore_table_job --params table=gold.acquirer_status,version=<good version>
```

In dev the same `RESTORE TABLE ... TO VERSION AS OF` runs directly in the SQL editor (11 s).

## 4. Repair: recompute silver from bronze

`RESTORE` is not supported on pipeline streaming tables. Bronze keeps every raw row, so a
selective full refresh recomputes `silver.payments` (about 1 to 1.5 minutes on this data) and
refreshes the gold materialized views in the same update. In the pipeline UI choose
**Select tables for refresh → Full refresh selection**, or:

```bash
databricks bundle run -t prod dlc \
  --full-refresh meridian.silver.payments \
  --refresh meridian.gold.payment_failure_daily,meridian.gold.acquirer_hourly,meridian.gold.merchant_daily
```

The refresh's own write fires the table-update trigger again, so `gold.acquirer_status` is rebuilt from
the repaired silver (and matches the restored version).

## 5. Verify

`scripts/backfill_drill.py --target <t>` reports PASS when the corrupted day's row count and total equal
the version before the bad write, and `gold.acquirer_status` shows a `RESTORE`.

## Limits to state

- Lineage is captured when code reads and writes tables by name; code that reads a raw cloud path
  produces no table edge. DML into a pipeline streaming table from a job is not a lineage write edge.
  Table history is the record of writes.
- System tables are not real-time; the table history is.
- A full refresh applies the contract as it is now. Rows that the reprocess job released under an older
  rule set are recomputed under the current rules.
- Code rollback does not roll back data, and RESTORE of a streaming table is not available; recovery of
  pipeline tables is a refresh (or reprocess), recovery of ordinary tables is `RESTORE`.
