-- Governed workflow (T18, BUILD on SQL stored procedures). Applied through a SQL warehouse by
-- src/meridian/jobs/workflow_setup.py, so the procedures are owned by the deploying identity. Every procedure is
-- SQL SECURITY DEFINER: callers need only EXECUTE, never direct table access, and session_user() inside is the
-- real caller. Amounts are computed from data here, never passed in by the model.
-- ${agent}, ${kb}, ${silver}: catalog.schema names. ${refund_threshold}: SGD amount above which approval is needed.
-- Inside a DEFINER procedure is_account_group_member() checks the owner, not the caller (observed 2026-10-16),
-- so approver checks use session_user() against agent.approvers, mirrored from meridian-admin by an admin
-- (apply_governance.py), and entitlement checks use agent.tier_members, mirrored from the tier groups the same way.
-- A run (start_run) is pinned to the latest approved workflow version and owned by whoever started it; every
-- later step checks both. Steps the agent performs itself (data, knowledge, status checks) are logged with
-- log_step; the others log themselves.

CREATE TABLE IF NOT EXISTS ${kb}.workflows (
  workflow_id STRING, version INT, status STRING, title STRING, owner STRING, approved_by STRING,
  approved_at TIMESTAMP, steps STRING, checksum STRING, change_note STRING, loaded_at TIMESTAMP)
COMMENT 'BUILD: runbook workflows; the agent executes only the latest approved version';

CREATE TABLE IF NOT EXISTS ${agent}.step_log (
  logged_at TIMESTAMP, run_id STRING, workflow_id STRING, version INT, step_id STRING, status STRING,
  detail STRING, logged_by STRING)
COMMENT 'BUILD: workflow steps completed per agent run';

CREATE TABLE IF NOT EXISTS ${agent}.impacts (
  computed_at TIMESTAMP, run_id STRING, acquirer_id STRING, window_hours INT, payments BIGINT,
  total_sgd DECIMAL(18, 2), computed_by STRING)
COMMENT 'BUILD: refundable impact per run, computed from silver.payments';

CREATE TABLE IF NOT EXISTS ${agent}.refund_batches (
  batch_id STRING, run_id STRING, acquirer_id STRING, payments BIGINT, total_sgd DECIMAL(18, 2), status STRING,
  proposed_by STRING, proposed_at TIMESTAMP, executed_by STRING, executed_at TIMESTAMP)
COMMENT 'BUILD: refund batches proposed by agent runs; totals come from agent.impacts';

CREATE TABLE IF NOT EXISTS ${agent}.approvals (
  approval_id STRING, run_id STRING, batch_id STRING, total_sgd DECIMAL(18, 2), status STRING,
  requested_by STRING, requested_at TIMESTAMP, approved_by STRING, decided_at TIMESTAMP, expires_at TIMESTAMP)
COMMENT 'BUILD: human approvals of refund batches; the approver must differ from the requester';

CREATE TABLE IF NOT EXISTS ${agent}.violations (
  at TIMESTAMP, run_id STRING, attempted STRING, reason STRING, caller STRING)
COMMENT 'BUILD: refused actions, written before the refusal is raised';

CREATE TABLE IF NOT EXISTS ${agent}.approvers (principal STRING, group_name STRING, synced_at TIMESTAMP)
COMMENT 'BUILD: members of meridian-admin as session_user() reports them (emails, service principal IDs)';

CREATE TABLE IF NOT EXISTS ${agent}.tier_members (principal STRING, tier STRING, synced_at TIMESTAMP)
COMMENT 'BUILD: who is entitled to each knowledge tier (members of its groups), as session_user() reports them';

CREATE TABLE IF NOT EXISTS ${agent}.runs (
  run_id STRING, workflow_id STRING, version INT, acquirer_id STRING, window_hours INT, started_by STRING,
  started_at TIMESTAMP)
COMMENT 'BUILD: workflow runs, each pinned when it starts to the latest approved version of its workflow';

CREATE TABLE IF NOT EXISTS ${kb}.audit_log (
  ts TIMESTAMP, actor STRING, action STRING, target STRING, reason STRING, details STRING)
COMMENT 'BUILD: who changed governed knowledge and workflows, when and why';

-- The latest approved version only; drafts are never returned.
CREATE OR REPLACE PROCEDURE ${agent}.get_workflow(IN p_workflow_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Latest approved version of a workflow (drafts are never returned)'
AS BEGIN
  SELECT workflow_id, version, title, steps, checksum FROM ${kb}.workflows
  WHERE workflow_id = p_workflow_id AND status = 'approved'
  ORDER BY version DESC LIMIT 1;
END;

CREATE OR REPLACE PROCEDURE ${agent}.approve_workflow(IN p_workflow_id STRING, IN p_version INT, IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Approve a draft workflow version: admins only, and never the version''s owner'
AS BEGIN
  DECLARE v_owner STRING;
  SET v_owner = (SELECT max(owner) FROM ${kb}.workflows WHERE workflow_id = p_workflow_id AND version = p_version
                 AND status = 'draft');
  IF v_owner IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no draft with that workflow and version';
  END IF;
  IF (SELECT count(*) FROM ${agent}.approvers WHERE principal = session_user()) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'only meridian-admin can approve workflows';
  END IF;
  IF v_owner = session_user() THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'the owner of a version cannot approve it';
  END IF;
  UPDATE ${kb}.workflows SET status = 'retired' WHERE workflow_id = p_workflow_id AND status = 'approved';
  UPDATE ${kb}.workflows SET status = 'approved', approved_by = session_user(), approved_at = current_timestamp()
  WHERE workflow_id = p_workflow_id AND version = p_version;
  INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), 'approve_workflow',
    p_workflow_id || ' v' || p_version, p_reason, NULL);
END;

CREATE OR REPLACE VIEW ${agent}.run_steps
COMMENT 'BUILD: the steps of each run''s pinned workflow version, in order'
AS SELECT run_id, started_by, pos, step.id AS step_id, step.tool AS tool, step.tier AS tier
FROM (SELECT r.run_id, r.started_by,
             posexplode(from_json(w.steps, 'array<struct<id:string,tool:string,tier:string>>')) AS (pos, step)
      FROM ${agent}.runs r JOIN ${kb}.workflows w ON w.workflow_id = r.workflow_id AND w.version = r.version);

CREATE OR REPLACE PROCEDURE ${agent}.start_run(IN p_workflow_id STRING, IN p_acquirer_id STRING,
                                               IN p_window_hours INT)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Start a run of the latest approved version of a workflow for an acquirer and a window in hours'
AS BEGIN
  DECLARE v_version INT;
  DECLARE v_run STRING;
  SET v_version = (SELECT max(version) FROM ${kb}.workflows WHERE workflow_id = p_workflow_id AND status = 'approved');
  IF v_version IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no approved version of that workflow';
  END IF;
  IF coalesce(p_window_hours, 0) <= 0
     OR (SELECT count(*) FROM ${silver}.payments WHERE acquirer_id = p_acquirer_id) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'unknown acquirer, or the window is not a positive number of hours';
  END IF;
  SET v_run = 'run-' || substr(replace(uuid(), '-', ''), 1, 12);
  INSERT INTO ${agent}.runs VALUES (v_run, p_workflow_id, v_version, p_acquirer_id, p_window_hours, session_user(),
    current_timestamp());
  SELECT r.run_id, r.workflow_id, r.version, w.title, w.steps FROM ${agent}.runs r
  JOIN ${kb}.workflows w ON w.workflow_id = r.workflow_id AND w.version = r.version WHERE r.run_id = v_run;
END;

CREATE OR REPLACE PROCEDURE ${agent}.get_run(IN p_run_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'One of the caller''s own runs: workflow version and steps, parameters, steps logged, batch and approval'
AS BEGIN
  SELECT r.run_id, r.workflow_id, r.version, w.title, w.steps, r.acquirer_id, r.window_hours,
    (SELECT to_json(collect_list(named_struct('at', logged_at, 'step_id', step_id, 'status', status)))
     FROM ${agent}.step_log WHERE run_id = p_run_id) AS logged,
    b.batch_id, b.total_sgd, b.status AS batch_status, a.approval_id, a.status AS approval_status, a.expires_at
  FROM ${agent}.runs r
  JOIN ${kb}.workflows w ON w.workflow_id = r.workflow_id AND w.version = r.version
  LEFT JOIN (SELECT * FROM ${agent}.refund_batches WHERE run_id = p_run_id ORDER BY proposed_at DESC LIMIT 1) b
    ON true
  LEFT JOIN (SELECT * FROM ${agent}.approvals WHERE run_id = p_run_id ORDER BY requested_at DESC LIMIT 1) a ON true
  WHERE r.run_id = p_run_id AND r.started_by = session_user();
END;

-- Steps the agent performs itself; a step that reads a restricted tier needs the caller to be entitled to it.
CREATE OR REPLACE PROCEDURE ${agent}.log_step(IN p_run_id STRING, IN p_step_id STRING, IN p_status STRING,
                                              IN p_detail STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Record a step the agent performs itself (data, knowledge, status check) for one of the caller''s runs'
AS BEGIN
  DECLARE v_tool STRING;
  DECLARE v_tier STRING;
  SET v_tool = (SELECT max(tool) FROM ${agent}.run_steps WHERE run_id = p_run_id AND started_by = session_user()
                AND step_id = p_step_id);
  SET v_tier = (SELECT max(tier) FROM ${agent}.run_steps WHERE run_id = p_run_id AND started_by = session_user()
                AND step_id = p_step_id);
  IF v_tool IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no run with that id started by you, or no such step in its workflow';
  END IF;
  IF v_tool NOT IN ('ask_genie', 'search_kb', 'check_acquirer_status') THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'log_step ' || p_step_id,
      'tried to log a step that logs itself', session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: only steps the agent performs itself are logged here';
  END IF;
  IF p_status = 'ok' AND v_tier IS NOT NULL
     AND (SELECT count(*) FROM ${agent}.tier_members WHERE principal = session_user() AND tier = v_tier) = 0 THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'log_step ' || p_step_id,
      'caller is not entitled to the ' || v_tier || ' tier', session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: you are not entitled to the knowledge this step reads';
  END IF;
  INSERT INTO ${agent}.step_log SELECT current_timestamp(), run_id, workflow_id, version, p_step_id, p_status,
    p_detail, session_user() FROM ${agent}.runs WHERE run_id = p_run_id;
END;

-- Refusals by the agent's step guard (layer 1); refusals by the procedures here log themselves.
CREATE OR REPLACE PROCEDURE ${agent}.log_violation(IN p_run_id STRING, IN p_attempted STRING, IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Record an action the agent''s step guard refused'
AS BEGIN
  INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'agent guard: ' || p_attempted, p_reason,
    session_user());
END;

CREATE OR REPLACE PROCEDURE ${agent}.compute_impact(IN p_run_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's3: value of failed payments with refundable codes for the run''s acquirer and window, from silver.payments'
AS BEGIN
  DECLARE v_acquirer STRING;
  DECLARE v_hours INT;
  DECLARE v_reason STRING;
  SET v_acquirer = (SELECT max(acquirer_id) FROM ${agent}.runs WHERE run_id = p_run_id AND started_by = session_user());
  SET v_hours = (SELECT max(window_hours) FROM ${agent}.runs WHERE run_id = p_run_id AND started_by = session_user());
  SET v_reason = CASE
    WHEN v_acquirer IS NULL THEN 'no run ' || p_run_id || ' started by the caller'
    WHEN (SELECT count(*) FROM ${agent}.run_steps WHERE run_id = p_run_id
          AND tool IN ('ask_genie', 'search_kb', 'check_acquirer_status')
          AND step_id NOT IN (SELECT step_id FROM ${agent}.step_log WHERE run_id = p_run_id AND status = 'ok')) > 0
      THEN 'the data and knowledge steps before s3 are not all complete'
  END;
  IF v_reason IS NOT NULL THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'compute_impact', v_reason, session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: ' || v_reason;
  END IF;
  INSERT INTO ${agent}.impacts
  SELECT current_timestamp(), p_run_id, v_acquirer, v_hours, count(*), coalesce(sum(p.amount), 0), session_user()
  FROM ${silver}.payments p
  WHERE p.acquirer_id = v_acquirer AND p.status = 'failed'
    AND p.failure_code IN ('issuer_unavailable', 'timeout')
    AND p.created_at >= (SELECT max(created_at) FROM ${silver}.payments) - make_interval(0, 0, 0, 0, v_hours);
  INSERT INTO ${agent}.step_log SELECT current_timestamp(), run_id, workflow_id, version, 's3', 'ok',
    'impact computed from data', session_user() FROM ${agent}.runs WHERE run_id = p_run_id;
  SELECT payments, total_sgd FROM ${agent}.impacts WHERE run_id = p_run_id ORDER BY computed_at DESC LIMIT 1;
END;

CREATE OR REPLACE PROCEDURE ${agent}.propose_refund(IN p_run_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's4: one refund batch per run, with the total taken from the computed impact'
AS BEGIN
  DECLARE v_reason STRING;
  SET v_reason = CASE
    WHEN (SELECT count(*) FROM ${agent}.runs WHERE run_id = p_run_id AND started_by = session_user()) = 0
      THEN 'no run ' || p_run_id || ' started by the caller'
    WHEN (SELECT count(*) FROM ${agent}.step_log WHERE run_id = p_run_id AND step_id = 's3' AND status = 'ok') = 0
      THEN 'compute the impact (s3) before proposing a refund'
    WHEN (SELECT count(*) FROM ${agent}.refund_batches WHERE run_id = p_run_id) > 0
      THEN 'a batch was already proposed for this run'
  END;
  IF v_reason IS NOT NULL THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'propose_refund', v_reason, session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: ' || v_reason;
  END IF;
  INSERT INTO ${agent}.refund_batches
  SELECT 'RB-' || substr(sha2(p_run_id || cast(current_timestamp() AS STRING), 256), 1, 10), p_run_id, acquirer_id,
         payments, total_sgd, 'proposed', session_user(), current_timestamp(), NULL, NULL
  FROM (SELECT * FROM ${agent}.impacts WHERE run_id = p_run_id ORDER BY computed_at DESC LIMIT 1);
  INSERT INTO ${agent}.step_log SELECT current_timestamp(), run_id, workflow_id, version, 's4', 'ok',
    'refund batch proposed', session_user() FROM ${agent}.runs WHERE run_id = p_run_id;
  SELECT batch_id, payments, total_sgd FROM ${agent}.refund_batches WHERE run_id = p_run_id
  ORDER BY proposed_at DESC LIMIT 1;
END;

CREATE OR REPLACE PROCEDURE ${agent}.request_approval(IN p_run_id STRING, IN p_batch_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's5: ask meridian-admin to approve a batch above the threshold; approvals expire after 48 hours'
AS BEGIN
  DECLARE v_total DECIMAL(18, 2);
  SET v_total = (SELECT max(b.total_sgd) FROM ${agent}.refund_batches b JOIN ${agent}.runs r ON r.run_id = b.run_id
                 WHERE b.batch_id = p_batch_id AND b.run_id = p_run_id AND b.status = 'proposed'
                 AND r.started_by = session_user());
  IF v_total IS NULL THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'request_approval',
      'no proposed batch ' || p_batch_id || ' in a run started by the caller', session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: no proposed batch with that id in a run you started';
  END IF;
  IF v_total <= ${refund_threshold} THEN
    INSERT INTO ${agent}.step_log SELECT current_timestamp(), run_id, workflow_id, version, 's5', 'not_required',
      'total at or below the threshold', session_user() FROM ${agent}.runs WHERE run_id = p_run_id;
    SELECT 'not_required' AS status, CAST(NULL AS STRING) AS approval_id, v_total AS total_sgd;
  ELSE
    INSERT INTO ${agent}.approvals VALUES ('AP-' || substr(sha2(p_batch_id || cast(current_timestamp() AS STRING), 256), 1, 10),
      p_run_id, p_batch_id, v_total, 'pending', session_user(), current_timestamp(), NULL, NULL,
      current_timestamp() + INTERVAL 48 HOURS);
    INSERT INTO ${agent}.step_log SELECT current_timestamp(), run_id, workflow_id, version, 's5', 'pending',
      'approval requested', session_user() FROM ${agent}.runs WHERE run_id = p_run_id;
    SELECT 'pending_approval' AS status, approval_id, total_sgd FROM ${agent}.approvals
    WHERE batch_id = p_batch_id ORDER BY requested_at DESC LIMIT 1;
  END IF;
END;

-- A person, not the agent: meridian-admin, never the requester, before expiry.
CREATE OR REPLACE PROCEDURE ${agent}.approve_refund(IN p_approval_id STRING, IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Approve a pending refund batch: meridian-admin only, never the requester, before it expires'
AS BEGIN
  DECLARE v_requester STRING;
  SET v_requester = (SELECT max(requested_by) FROM ${agent}.approvals WHERE approval_id = p_approval_id
                     AND status = 'pending' AND expires_at > current_timestamp());
  IF v_requester IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no pending, unexpired approval with that id';
  END IF;
  IF (SELECT count(*) FROM ${agent}.approvers WHERE principal = session_user()) = 0 THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), NULL, 'approve_refund ' || p_approval_id,
      'approver is not in meridian-admin', session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'only meridian-admin can approve refunds';
  END IF;
  IF v_requester = session_user() THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), NULL, 'approve_refund ' || p_approval_id,
      'requester tried to approve their own refund', session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'the requester cannot approve their own refund';
  END IF;
  UPDATE ${agent}.approvals SET status = 'approved', approved_by = session_user(), decided_at = current_timestamp()
  WHERE approval_id = p_approval_id;
  INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), 'approve_refund', p_approval_id, p_reason,
    NULL);
END;

-- s6: the only way to execute a refund. Every precondition is checked here, whatever the agent claims.
CREATE OR REPLACE PROCEDURE ${agent}.refund_batch(IN p_run_id STRING, IN p_batch_id STRING, IN p_approval_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's6: execute a proposed batch when the earlier steps are complete and, above the threshold, a valid approval exists'
AS BEGIN
  DECLARE v_total DECIMAL(18, 2);
  DECLARE v_reason STRING;
  SET v_total = (SELECT max(total_sgd) FROM ${agent}.refund_batches WHERE batch_id = p_batch_id AND run_id = p_run_id
                 AND status = 'proposed');
  SET v_reason = CASE
    WHEN (SELECT count(*) FROM ${agent}.runs WHERE run_id = p_run_id AND started_by = session_user()) = 0
      THEN 'no run ' || p_run_id || ' started by the caller'
    WHEN v_total IS NULL THEN 'no proposed batch ' || p_batch_id || ' for run ' || p_run_id
    WHEN (SELECT count(*) FROM ${agent}.run_steps WHERE run_id = p_run_id
          AND tool NOT IN ('request_approval', 'refund_batch')
          AND step_id NOT IN (SELECT step_id FROM ${agent}.step_log WHERE run_id = p_run_id AND status = 'ok')) > 0
      THEN 'the earlier steps of the run are not all complete'
    WHEN v_total > ${refund_threshold} AND (SELECT count(*) FROM ${agent}.approvals WHERE approval_id = p_approval_id
          AND batch_id = p_batch_id AND status = 'approved' AND expires_at > current_timestamp()
          AND approved_by <> requested_by AND total_sgd = v_total) = 0
      THEN 'no valid approval for this batch and total'
  END;
  IF v_reason IS NOT NULL THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'refund_batch ' || p_batch_id, v_reason,
      session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: ' || v_reason;
  END IF;
  UPDATE ${agent}.refund_batches SET status = 'executed', executed_by = session_user(), executed_at = current_timestamp()
  WHERE batch_id = p_batch_id;
  INSERT INTO ${agent}.step_log SELECT current_timestamp(), run_id, workflow_id, version, 's6', 'ok', 'refund executed',
    session_user() FROM ${agent}.runs WHERE run_id = p_run_id;
  INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), 'refund_batch', p_batch_id,
    'approval ' || coalesce(p_approval_id, 'not required'), NULL);
  SELECT batch_id, total_sgd, status FROM ${agent}.refund_batches WHERE batch_id = p_batch_id;
END;
