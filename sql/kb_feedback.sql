-- Feedback and corrections (T20, BUILD on SQL stored procedures). Applied after sql/workflow_objects.sql by
-- src/meridian/jobs/workflow_setup.py; the tables live in sql/kb_objects.sql (kb_sync creates them). Every
-- procedure is SQL SECURITY DEFINER, so callers need only EXECUTE and session_user() is the caller.
-- Anyone may give feedback, and propose a correction to a tier they are entitled to (agent.tier_members).
-- meridian-admin (agent.approvers) approves, never the submitter; rejects; or reverts an approved correction.
-- Approved corrections are served: kb.v_source_docs includes them, so kb_sync indexes them and drops them on
-- revert. Every decision is written to kb.audit_log.
-- ${agent}, ${kb}: catalog.schema names.

CREATE OR REPLACE PROCEDURE ${kb}.submit_feedback(IN p_question STRING, IN p_answer STRING, IN p_rating STRING,
                                                 IN p_comment STRING, IN p_invocation_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Record feedback on an answer: up or down, with a comment'
AS BEGIN
  DECLARE v_id STRING;
  IF coalesce(p_rating, '') NOT IN ('up', 'down') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rating must be up or down';
  END IF;
  SET v_id = 'FB-' || upper(substr(replace(uuid(), '-', ''), 1, 10));
  INSERT INTO ${kb}.feedback VALUES (v_id, current_timestamp(), session_user(), p_question, p_answer, p_rating,
    p_comment, p_invocation_id);
  SELECT v_id AS feedback_id;
END;

CREATE OR REPLACE PROCEDURE ${kb}.submit_correction(IN p_tier STRING, IN p_title STRING, IN p_text STRING,
                                                   IN p_corrects_doc_id STRING, IN p_reason STRING,
                                                   IN p_feedback_id STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Propose a correction to the knowledge base for a tier the caller is entitled to'
AS BEGIN
  DECLARE v_id STRING;
  IF (SELECT count(*) FROM ${agent}.tier_members WHERE principal = session_user() AND tier = p_tier) = 0 THEN
    INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), 'submit_correction refused', p_tier,
      'caller is not entitled to the ' || coalesce(p_tier, 'unknown') || ' tier', p_title);
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: you can only correct a tier you are entitled to';
  END IF;
  IF length(trim(coalesce(p_title, ''))) = 0 OR length(trim(coalesce(p_text, ''))) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'a correction needs a title and a text';
  END IF;
  SET v_id = 'CORR-' || upper(substr(replace(uuid(), '-', ''), 1, 8));  -- cited like DOC- ids
  INSERT INTO ${kb}.corrections VALUES (v_id, 1, 'proposed', p_tier, p_title, p_text, p_corrects_doc_id, p_reason,
    p_feedback_id, session_user(), current_timestamp(), NULL, NULL, NULL);
  INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), 'submit_correction', v_id, p_reason,
    p_title);
  SELECT v_id AS correction_id, 'proposed' AS status;
END;

-- A decision by a person in meridian-admin: approve or reject a proposed correction, or revert an approved one.
CREATE OR REPLACE PROCEDURE ${kb}.decide_correction(IN p_correction_id STRING, IN p_decision STRING,
                                                   IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'meridian-admin approves or rejects a proposed correction (never their own), or reverts an approved one'
AS BEGIN
  DECLARE v_status STRING;
  DECLARE v_submitter STRING;
  DECLARE v_reason STRING;
  SET v_status = (SELECT max(status) FROM ${kb}.corrections WHERE correction_id = p_correction_id);
  SET v_submitter = (SELECT max(submitted_by) FROM ${kb}.corrections WHERE correction_id = p_correction_id);
  SET v_reason = CASE
    WHEN v_status IS NULL THEN 'no correction ' || p_correction_id
    WHEN (SELECT count(*) FROM ${agent}.approvers WHERE principal = session_user()) = 0
      THEN 'only meridian-admin can decide corrections'
    WHEN coalesce(p_decision, '') NOT IN ('approve', 'reject', 'revert') THEN 'decision must be approve, reject or revert'
    WHEN p_decision IN ('approve', 'reject') AND v_status <> 'proposed'
      THEN 'only a proposed correction can be approved or rejected (it is ' || v_status || ')'
    WHEN p_decision = 'revert' AND v_status <> 'approved'
      THEN 'only an approved correction can be reverted (it is ' || v_status || ')'
    WHEN p_decision = 'approve' AND v_submitter = session_user() THEN 'the submitter cannot approve their own correction'
  END;
  IF v_reason IS NOT NULL THEN
    INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(),
      'decide_correction refused', p_correction_id, v_reason, p_decision);
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'refused: ' || v_reason;
  END IF;
  UPDATE ${kb}.corrections SET status = CASE p_decision WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected'
                                                        ELSE 'reverted' END,
         decided_by = session_user(), decided_at = current_timestamp(), decision_reason = p_reason
  WHERE correction_id = p_correction_id;
  INSERT INTO ${kb}.audit_log VALUES (current_timestamp(), session_user(), p_decision || '_correction', p_correction_id,
    p_reason, NULL);
  SELECT correction_id, status, decided_by FROM ${kb}.corrections WHERE correction_id = p_correction_id;
END;

-- The named decisions. A nested CALL keeps session_user() as the original caller (observed 2026-10-17).
CREATE OR REPLACE PROCEDURE ${kb}.approve_correction(IN p_correction_id STRING, IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'meridian-admin approves a proposed correction; never the submitter'
AS BEGIN
  CALL ${kb}.decide_correction(p_correction_id, 'approve', p_reason);
END;

CREATE OR REPLACE PROCEDURE ${kb}.reject_correction(IN p_correction_id STRING, IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'meridian-admin rejects a proposed correction'
AS BEGIN
  CALL ${kb}.decide_correction(p_correction_id, 'reject', p_reason);
END;

CREATE OR REPLACE PROCEDURE ${kb}.revert_correction(IN p_correction_id STRING, IN p_reason STRING)
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'meridian-admin reverts an approved correction; the next kb_sync stops serving it'
AS BEGIN
  CALL ${kb}.decide_correction(p_correction_id, 'revert', p_reason);
END;

-- What a caller may see of corrections: their own, plus every decision if they are in meridian-admin.
CREATE OR REPLACE PROCEDURE ${kb}.list_corrections()
LANGUAGE SQL SQL SECURITY DEFINER
COMMENT 'Corrections the caller submitted; meridian-admin sees all of them'
AS BEGIN
  SELECT correction_id, version, status, tier, title, submitted_by, submitted_at, decided_by, decided_at
  FROM ${kb}.corrections
  WHERE submitted_by = session_user() OR (SELECT count(*) FROM ${agent}.approvers WHERE principal = session_user()) > 0
  ORDER BY submitted_at DESC;
END;
