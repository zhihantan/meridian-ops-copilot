-- Governed workflow (T18, BUILD on SQL stored procedures). Applied through a SQL warehouse by
-- src/meridian/jobs/apply_sql.py, so the procedures are owned by the deploying identity. Every procedure is
-- SQL SECURITY DEFINER: callers need only EXECUTE, never direct table access, and session_user() inside is the
-- real caller. Amounts are computed from data here, never passed in by the model.
-- ${agent}, ${kb}, ${silver}: catalog.schema names. ${refund_threshold}: SGD amount above which approval is needed.
-- Inside a DEFINER procedure is_account_group_member() checks the owner, not the caller (observed 2026-10-16),
-- so approver checks use session_user() against agent.approvers, synced from meridian-admin by the setup job.

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

-- Steps the agent performs itself (s1 data, s2 knowledge); the procedures below log their own steps.
CREATE OR REPLACE PROCEDURE ${agent}.log_step(IN p_run_id STRING, IN p_workflow_id STRING, IN p_version INT,
                                              IN p_step_id STRING, IN p_status STRING, IN p_detail STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Record a completed workflow step for an agent run'
AS BEGIN
  IF p_step_id NOT IN ('s1', 's2') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'only s1 and s2 are logged by the agent; later steps log themselves';
  END IF;
  INSERT INTO ${agent}.step_log VALUES (current_timestamp(), p_run_id, p_workflow_id, p_version, p_step_id, p_status,
    p_detail, session_user());
END;

CREATE OR REPLACE PROCEDURE ${agent}.compute_impact(IN p_run_id STRING, IN p_acquirer_id STRING, IN p_window_hours INT)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's3: value of failed payments with refundable codes for the acquirer in the window, from silver.payments'
AS BEGIN
  INSERT INTO ${agent}.impacts
  SELECT current_timestamp(), p_run_id, p_acquirer_id, p_window_hours, count(*), coalesce(sum(p.amount), 0),
         session_user()
  FROM ${silver}.payments p
  WHERE p.acquirer_id = p_acquirer_id AND p.status = 'failed'
    AND p.failure_code IN ('issuer_unavailable', 'timeout')
    AND p.created_at >= (SELECT max(created_at) FROM ${silver}.payments) - make_interval(0, 0, 0, 0, p_window_hours);
  INSERT INTO ${agent}.step_log VALUES (current_timestamp(), p_run_id, 'RB-014', NULL, 's3', 'ok',
    'impact computed from data', session_user());
  SELECT payments, total_sgd FROM ${agent}.impacts WHERE run_id = p_run_id ORDER BY computed_at DESC LIMIT 1;
END;

CREATE OR REPLACE PROCEDURE ${agent}.propose_refund(IN p_run_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's4: a refund batch for the run, with the total taken from the computed impact'
AS BEGIN
  IF (SELECT count(*) FROM ${agent}.step_log WHERE run_id = p_run_id AND step_id = 's3' AND status = 'ok') = 0 THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'propose_refund', 's3 not completed',
      session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: compute the impact (s3) before proposing a refund';
  END IF;
  INSERT INTO ${agent}.refund_batches
  SELECT 'RB-' || substr(sha2(p_run_id || cast(current_timestamp() AS STRING), 256), 1, 10), p_run_id, acquirer_id,
         payments, total_sgd, 'proposed', session_user(), current_timestamp(), NULL, NULL
  FROM (SELECT * FROM ${agent}.impacts WHERE run_id = p_run_id ORDER BY computed_at DESC LIMIT 1);
  INSERT INTO ${agent}.step_log VALUES (current_timestamp(), p_run_id, 'RB-014', NULL, 's4', 'ok',
    'refund batch proposed', session_user());
  SELECT batch_id, payments, total_sgd FROM ${agent}.refund_batches WHERE run_id = p_run_id
  ORDER BY proposed_at DESC LIMIT 1;
END;

CREATE OR REPLACE PROCEDURE ${agent}.request_approval(IN p_run_id STRING, IN p_batch_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 's5: ask meridian-admin to approve a batch above the threshold; approvals expire after 48 hours'
AS BEGIN
  DECLARE v_total DECIMAL(18, 2);
  SET v_total = (SELECT max(total_sgd) FROM ${agent}.refund_batches WHERE batch_id = p_batch_id AND run_id = p_run_id
                 AND status = 'proposed');
  IF v_total IS NULL THEN
    INSERT INTO ${agent}.violations VALUES (current_timestamp(), p_run_id, 'request_approval',
      'no proposed batch ' || p_batch_id || ' for this run', session_user());
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: no proposed batch with that id for this run';
  END IF;
  IF v_total <= ${refund_threshold} THEN
    INSERT INTO ${agent}.step_log VALUES (current_timestamp(), p_run_id, 'RB-014', NULL, 's5', 'not_required',
      'total at or below the threshold', session_user());
    SELECT 'not_required' AS status, CAST(NULL AS STRING) AS approval_id, v_total AS total_sgd;
  ELSE
    INSERT INTO ${agent}.approvals VALUES ('AP-' || substr(sha2(p_batch_id || cast(current_timestamp() AS STRING), 256), 1, 10),
      p_run_id, p_batch_id, v_total, 'pending', session_user(), current_timestamp(), NULL, NULL,
      current_timestamp() + INTERVAL 48 HOURS);
    INSERT INTO ${agent}.step_log VALUES (current_timestamp(), p_run_id, 'RB-014', NULL, 's5', 'pending',
      'approval requested', session_user());
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
COMMENT 's6: execute a proposed batch when s1 to s5 are complete and, above the threshold, a valid approval exists'
AS BEGIN
  DECLARE v_total DECIMAL(18, 2);
  DECLARE v_reason STRING;
  SET v_total = (SELECT max(total_sgd) FROM ${agent}.refund_batches WHERE batch_id = p_batch_id AND run_id = p_run_id
                 AND status = 'proposed');
  SET v_reason = CASE
    WHEN v_total IS NULL THEN 'no proposed batch ' || p_batch_id || ' for run ' || p_run_id
    WHEN (SELECT count(DISTINCT step_id) FROM ${agent}.step_log WHERE run_id = p_run_id
          AND step_id IN ('s1', 's2', 's3', 's4') AND status = 'ok') < 4 THEN 'steps s1 to s4 are not all complete'
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
  INSERT INTO ${agent}.step_log VALUES (current_timestamp(), p_run_id, 'RB-014', NULL, 's6', 'ok', 'refund executed',
    session_user());
  INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), 'refund_batch', p_batch_id,
    'approval ' || coalesce(p_approval_id, 'not required'), NULL);
  SELECT batch_id, total_sgd, status FROM ${agent}.refund_batches WHERE batch_id = p_batch_id;
END;
