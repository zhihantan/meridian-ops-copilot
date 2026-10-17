-- Knowledge provenance views (T21), applied by meridian-daily (its kb_views task) before the audit export. Separate from
-- obs_views.sql because they read the kb schema, which only targets with a knowledge base have (dev and prod).

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
