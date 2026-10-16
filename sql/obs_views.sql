-- Centralized logs and metadata (T06b, BUILD views over native sources). Applied by
-- src/meridian/jobs/obs_views.py, which fills in the ${...} placeholders for the target.
-- System tables are not real-time; the pipeline event log and the check tables are current.

-- Job runs of this bundle target (jobs are tagged project and target by the bundle).
CREATE OR REPLACE VIEW ${obs}.v_job_runs
COMMENT 'BUILD: job runs of this target from system.lakeflow (not real-time), one row per run.'
AS WITH jobs AS (
  SELECT job_id, name FROM system.lakeflow.jobs
  WHERE workspace_id = '${workspace_id}' AND tags['project'] = 'meridian-poc' AND tags['target'] = '${target}'
  QUALIFY row_number() OVER (PARTITION BY job_id ORDER BY change_time DESC) = 1)
SELECT r.job_id, j.name AS job_name, r.run_id,
       min(r.period_start_time) AS started_at, max(r.period_end_time) AS ended_at,
       timestampdiff(SECOND, min(r.period_start_time), max(r.period_end_time)) AS duration_s,
       max_by(r.trigger_type, r.period_end_time) AS trigger_type,
       max_by(r.result_state, r.period_end_time) AS result_state,
       max_by(r.termination_code, r.period_end_time) AS termination_code
FROM system.lakeflow.job_run_timeline r JOIN jobs j ON r.job_id = j.job_id
WHERE r.workspace_id = '${workspace_id}' AND r.period_start_time >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY r.job_id, j.name, r.run_id;

-- Task runs of the same jobs: which task failed, with its termination code.
CREATE OR REPLACE VIEW ${obs}.v_task_runs
COMMENT 'BUILD: task runs of this target from system.lakeflow (not real-time), one row per task run.'
AS SELECT t.job_id, j.job_name, t.job_run_id, t.task_key, t.run_id AS task_run_id,
          min(t.period_start_time) AS started_at, max(t.period_end_time) AS ended_at,
          timestampdiff(SECOND, min(t.period_start_time), max(t.period_end_time)) AS duration_s,
          max_by(t.result_state, t.period_end_time) AS result_state,
          max_by(t.termination_code, t.period_end_time) AS termination_code
FROM system.lakeflow.job_task_run_timeline t
JOIN (SELECT DISTINCT job_id, job_name FROM ${obs}.v_job_runs) j ON t.job_id = j.job_id
WHERE t.workspace_id = '${workspace_id}' AND t.period_start_time >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY t.job_id, j.job_name, t.job_run_id, t.task_key, t.run_id;

-- Pipeline event log, published as a table by the pipeline (current, not a system table).
CREATE OR REPLACE VIEW ${obs}.v_pipeline_events
COMMENT 'BUILD: the pipeline event log with update, flow, level, message and error.'
AS SELECT timestamp, event_type, level, origin.update_id AS update_id, origin.flow_name AS flow_name,
          message, error.exceptions[0].message AS error_message, details
FROM ${obs}.pipeline_event_log;

-- Native expectation metrics per flow and update, flattened from flow_progress events.
CREATE OR REPLACE VIEW ${obs}.v_expectation_metrics
COMMENT 'Native: expectation pass and fail counts per flow and update, from the pipeline event log.'
AS SELECT timestamp, update_id, flow_name, e.name AS expectation, e.dataset, e.passed_records, e.failed_records
FROM (SELECT timestamp, update_id, flow_name,
             explode(from_json(details:flow_progress.data_quality.expectations,
                               'ARRAY<STRUCT<name: STRING, dataset: STRING, passed_records: BIGINT, failed_records: BIGINT>>')) AS e
      FROM ${obs}.v_pipeline_events
      WHERE event_type = 'flow_progress' AND details:flow_progress.data_quality.expectations IS NOT NULL);

-- Queries against this target's catalog (system.query.history, not real-time).
CREATE OR REPLACE VIEW ${obs}.v_query_history
COMMENT 'BUILD: queries that reference this catalog, from system.query.history (not real-time).'
AS SELECT start_time, end_time, executed_by, statement_id, statement_type, execution_status,
          total_duration_ms, read_rows, produced_rows, error_message, compute.warehouse_id AS warehouse_id,
          left(statement_text, 500) AS statement_text
FROM system.query.history
WHERE workspace_id = '${workspace_id}' AND start_time >= current_timestamp() - INTERVAL 7 DAYS
  AND contains(lower(statement_text), '${catalog}.');

-- Audit events that name this catalog (system.access.audit, not real-time).
CREATE OR REPLACE VIEW ${obs}.v_audit
COMMENT 'BUILD: audit events that reference this catalog, from system.access.audit (not real-time).'
AS SELECT event_time, service_name, action_name, user_identity.email AS principal,
          request_params, response.status_code AS status_code, response.error_message AS error_message
FROM system.access.audit
WHERE workspace_id = '${workspace_id}' AND event_date >= current_date() - INTERVAL 7 DAYS
  AND contains(to_json(request_params), '${catalog}.');

-- One place to ask "what failed in the last 24 hours and why".
CREATE OR REPLACE VIEW ${obs}.v_pipeline_health
COMMENT 'BUILD: last 24h of job and task runs, pipeline errors, check breaches, quarantine counts and slow or failed queries.'
AS SELECT ended_at AS at, 'job_run' AS source, job_name AS name, CAST(run_id AS STRING) AS run_id,
          result_state AS status, termination_code AS detail, duration_s
   FROM ${obs}.v_job_runs WHERE ended_at >= current_timestamp() - INTERVAL 24 HOURS
UNION ALL
   SELECT ended_at, 'task_run', concat(job_name, '.', task_key), CAST(job_run_id AS STRING),
          result_state, termination_code, duration_s
   FROM ${obs}.v_task_runs
   WHERE ended_at >= current_timestamp() - INTERVAL 24 HOURS AND result_state <> 'SUCCEEDED'
UNION ALL
   SELECT timestamp, 'pipeline', coalesce(flow_name, 'update'), update_id, level,
          coalesce(error_message, message), CAST(NULL AS BIGINT)
   FROM ${obs}.v_pipeline_events
   WHERE timestamp >= current_timestamp() - INTERVAL 24 HOURS AND level IN ('ERROR', 'WARN')
UNION ALL
   SELECT checked_at, concat('check:', check_name), concat_ws('.', table_name, column_name), run_id,
          'BREACH', message, CAST(NULL AS BIGINT)
   FROM (SELECT check_name, checked_at, table_name, column_name, run_id, message, breached FROM ${obs}.drift_events
         UNION ALL SELECT check_name, checked_at, table_name, column_name, run_id, message, breached FROM ${obs}.freshness_events
         UNION ALL SELECT check_name, checked_at, table_name, column_name, run_id, message, breached FROM ${gov}.pii_coverage)
   WHERE breached AND checked_at >= current_timestamp() - INTERVAL 24 HOURS
UNION ALL
   SELECT max(_quarantined_at), 'quarantine', rule, CAST(NULL AS STRING), 'QUARANTINED',
          concat(count(*), ' payment rows'), CAST(NULL AS BIGINT)
   FROM ${quarantine}.payments LATERAL VIEW explode(_failed_rules) r AS rule
   WHERE _quarantined_at >= current_timestamp() - INTERVAL 24 HOURS AND reprocessed_at IS NULL
   GROUP BY rule
UNION ALL
   SELECT end_time, 'query', executed_by, statement_id, execution_status,
          coalesce(error_message, left(statement_text, 200)), total_duration_ms DIV 1000
   FROM ${obs}.v_query_history
   WHERE start_time >= current_timestamp() - INTERVAL 24 HOURS
     AND (execution_status = 'FAILED' OR total_duration_ms > 30000);

-- Provenance of every knowledge document (T21): its version and last sync from kb.docs, who last changed the
-- source and why (file writes and deletes in system.access.audit, correction decisions, Slack authors), and the
-- latest kb.audit_log entry. system.access.audit is not real-time: a very recent file write may not show yet.
-- Table-level change history (DESCRIBE HISTORY of kb.docs and kb.corrections) goes to the dated audit export.
CREATE OR REPLACE VIEW ${obs}.v_kb_changes
COMMENT 'BUILD: per knowledge document: version, last sync, last editor, time and reason of the last change.'
AS WITH file_changes AS (
  SELECT request_params['path'] AS path, action_name, user_identity.email AS editor, event_time
  FROM system.access.audit
  WHERE workspace_id = '${workspace_id}' AND event_date >= current_date() - INTERVAL 30 DAYS
    AND service_name = 'filesystem' AND action_name IN ('filesPut', 'filesDelete')
    AND request_params['path'] LIKE '/Volumes/${catalog}/%/kb/files/%'
  QUALIFY row_number() OVER (PARTITION BY request_params['path'] ORDER BY event_time DESC) = 1),
last_audit AS (
  SELECT target, actor, action, reason, ts FROM ${kb}.audit_log
  QUALIFY row_number() OVER (PARTITION BY target ORDER BY ts DESC) = 1)
SELECT d.doc_id, d.source, d.tier, d.title, d.source_version, d.revision, d.chunks,
       d.last_changed_at AS synced_at, d.deleted_at, d.run_id AS sync_run_id,
       CASE d.source WHEN 'correction' THEN c.decided_by WHEN 'volume' THEN f.editor
            ELSE regexp_extract(d.title, 'message from (.*)$', 1) END AS last_editor,
       CASE d.source WHEN 'correction' THEN c.decided_at WHEN 'volume' THEN f.event_time
            ELSE d.modified_at END AS edited_at,
       CASE d.source WHEN 'correction' THEN c.status || ': ' || coalesce(c.decision_reason, c.reason)
            WHEN 'volume' THEN coalesce(f.action_name, 'file written before the audit window')
            ELSE 'Slack message' END AS change,
       c.submitted_by AS correction_submitted_by, c.reason AS correction_reason,
       a.actor AS last_audit_actor, a.action AS last_audit_action, a.reason AS last_audit_reason,
       a.ts AS last_audit_at
FROM ${kb}.docs d
LEFT JOIN file_changes f ON f.path = replace(d.uri, 'dbfs:', '')
LEFT JOIN ${kb}.corrections c ON c.correction_id = d.doc_id
LEFT JOIN last_audit a ON a.target = d.doc_id;
