-- Knowledge base objects (T11, T12; BUILD). Applied by src/meridian/jobs/kb_sync.py before each run,
-- with ${kb} (catalog.schema) and ${kb_root} (the landing folder) filled in.

CREATE TABLE IF NOT EXISTS ${kb}.channel_tiers (channel STRING, tier STRING)
COMMENT 'Tier of each synced Slack channel; kb_sync rewrites it from config/scenario.yaml';

CREATE TABLE IF NOT EXISTS ${kb}.audit_log (
  ts TIMESTAMP, actor STRING, action STRING, target STRING, reason STRING, details STRING)
COMMENT 'BUILD: who changed governed knowledge and workflows, when and why: the procedures and kb_sync write it (T21)';

-- Feedback and corrections (T20). Written only through the procedures in sql/kb_feedback.sql. An approved
-- correction is a knowledge document in its own right (source 'correction'), served until it is reverted.
CREATE TABLE IF NOT EXISTS ${kb}.feedback (
  feedback_id STRING, ts TIMESTAMP, user STRING, question STRING, answer STRING, rating STRING, comment STRING,
  invocation_id STRING)
COMMENT 'BUILD: answer feedback (up or down) with the asker, the question and the answer';

CREATE TABLE IF NOT EXISTS ${kb}.corrections (
  correction_id STRING, version INT, status STRING, tier STRING, title STRING, text STRING, corrects_doc_id STRING,
  reason STRING, feedback_id STRING, submitted_by STRING, submitted_at TIMESTAMP, decided_by STRING,
  decided_at TIMESTAMP, decision_reason STRING)
COMMENT 'BUILD: proposed, approved, rejected and reverted corrections; approved ones are served as documents';

-- Source documents, normalized. Files: tier from the folder under kb/files/, title, version and date from
-- the source manifest when listed. Slack: one document per message from the history pages under
-- kb/slack/history/ (what a puller writes from conversations.history), tier from channel_tiers.
-- Corrections: approved ones only, so a revert removes the document on the next sync.
CREATE OR REPLACE VIEW ${kb}.v_source_docs
COMMENT 'BUILD: knowledge source documents as doc_id, source, uri, format, tier, title, source_version, modified_at, file_modified_at and content'
AS WITH files AS (
  SELECT path, modificationTime AS modified_at, content,
         regexp_extract(path, '/kb/files/([^/]+)/[^/]+$', 1) AS folder,
         regexp_extract(path, '/([^/]+)[.][A-Za-z0-9]+$', 1) AS doc_id,
         lower(regexp_extract(path, '[.]([A-Za-z0-9]+)$', 1)) AS format
  FROM read_files('${kb_root}/files/', format => 'binaryFile', recursiveFileLookup => true)
  WHERE path NOT LIKE '%/manifest.csv'),
manifest AS (
  SELECT doc_id, title, version, modified_at FROM read_files('${kb_root}/files/manifest.csv', format => 'csv', header => true)),
users AS (
  SELECT u.id, u.name FROM (SELECT explode(from_json(value, 'ARRAY<STRUCT<id: STRING, name: STRING>>')) AS u
                            FROM read_files('${kb_root}/slack/users/', format => 'text', wholeText => true))),
messages AS (
  SELECT h.channel.id AS channel_id, h.channel.name AS channel, h._metadata.file_modification_time AS file_modified_at, m.msg.*
  FROM read_files('${kb_root}/slack/history/', format => 'json', multiLine => true, recursiveFileLookup => true) h
  LATERAL VIEW explode(h.messages) m AS msg)
SELECT f.doc_id, 'volume' AS source, f.path AS uri, f.format,
       CASE WHEN f.folder IN ('general', 'finance') THEN f.folder END AS tier,
       coalesce(m.title, f.doc_id) AS title, CAST(m.version AS STRING) AS source_version,
       coalesce(to_timestamp(m.modified_at), f.modified_at) AS modified_at,   -- the source's date, else the file's
       f.modified_at AS file_modified_at, f.content AS content_bytes, CAST(NULL AS STRING) AS content_text
FROM files f LEFT JOIN manifest m ON f.doc_id = m.doc_id
UNION ALL
SELECT 'SLACK-' || coalesce(msg.msg_key, msg.channel_id || '-' || msg.ts) AS doc_id, 'slack' AS source,
       'slack://' || msg.channel || '/' || msg.ts AS uri, 'slack' AS format, t.tier,
       '#' || msg.channel || ' message from ' || coalesce(u.name, msg.user) AS title, CAST(NULL AS STRING),
       timestamp_seconds(CAST(msg.ts AS DOUBLE)) AS modified_at, msg.file_modified_at, CAST(NULL AS BINARY),
       coalesce(u.name, msg.user) || ' in #' || msg.channel
         || CASE WHEN msg.thread_ts IS NOT NULL AND msg.thread_ts <> msg.ts THEN ' (thread reply)' ELSE '' END
         || ': ' || msg.text AS content_text
FROM messages msg LEFT JOIN ${kb}.channel_tiers t ON msg.channel = t.channel LEFT JOIN users u ON msg.user = u.id
UNION ALL
SELECT c.correction_id, 'correction', 'correction://' || c.correction_id, 'correction', c.tier,
       'Correction: ' || c.title, CAST(c.version AS STRING), c.decided_at, c.decided_at, CAST(NULL AS BINARY),
       c.title || '\n\n' || c.text || coalesce('\n\nCorrects ' || c.corrects_doc_id || '.', '')
FROM ${kb}.corrections c WHERE c.status = 'approved';

CREATE TABLE IF NOT EXISTS ${kb}.docs (
  doc_id STRING, source STRING, uri STRING, format STRING, tier STRING, title STRING, source_version STRING,
  revision INT, content_hash STRING, chunks INT, modified_at TIMESTAMP, first_synced_at TIMESTAMP,
  last_changed_at TIMESTAMP, deleted_at TIMESTAMP, run_id STRING)
COMMENT 'BUILD: one row per knowledge document; revision increases on each content change; deleted_at when the source is gone';

CREATE TABLE IF NOT EXISTS ${kb}.chunks_general (
  chunk_id STRING NOT NULL, doc_id STRING, title STRING, source STRING, uri STRING, tier STRING, page INT, seq INT,
  text STRING, doc_revision INT, source_version STRING, modified_at TIMESTAMP, synced_at TIMESTAMP, run_id STRING)
COMMENT 'BUILD: retrieval chunks of general-tier documents; source of the general index'
TBLPROPERTIES (delta.enableChangeDataFeed = true);

CREATE TABLE IF NOT EXISTS ${kb}.chunks_finance (
  chunk_id STRING NOT NULL, doc_id STRING, title STRING, source STRING, uri STRING, tier STRING, page INT, seq INT,
  text STRING, doc_revision INT, source_version STRING, modified_at TIMESTAMP, synced_at TIMESTAMP, run_id STRING)
COMMENT 'BUILD: retrieval chunks of finance-tier documents; source of the finance index'
TBLPROPERTIES (delta.enableChangeDataFeed = true);

CREATE TABLE IF NOT EXISTS ${kb}.ingest_failures (
  failed_at TIMESTAMP, run_id STRING, doc_id STRING, uri STRING, stage STRING, reason STRING)
COMMENT 'BUILD: one row per document that could not be synced, with the stage and a readable reason';

CREATE TABLE IF NOT EXISTS ${kb}.sync_runs (
  started_at TIMESTAMP, finished_at TIMESTAMP, run_id STRING, full_refresh BOOLEAN, source_docs INT, new INT,
  changed INT, unchanged INT, deleted INT, failed INT, chunks_written INT, chunks_deleted INT)
COMMENT 'BUILD: one row per kb_sync run';

CREATE OR REPLACE VIEW ${kb}.sync_status
COMMENT 'BUILD: knowledge sync health: the last run, live documents and chunks per tier, failures in the last 24h'
AS SELECT r.finished_at AS last_run_at, r.run_id AS last_run_id, r.new, r.changed, r.unchanged, r.deleted, r.failed,
          (SELECT count(*) FROM ${kb}.docs WHERE deleted_at IS NULL AND tier = 'general') AS live_docs_general,
          (SELECT count(*) FROM ${kb}.docs WHERE deleted_at IS NULL AND tier = 'finance') AS live_docs_finance,
          (SELECT count(*) FROM ${kb}.chunks_general) AS chunks_general,
          (SELECT count(*) FROM ${kb}.chunks_finance) AS chunks_finance,
          (SELECT count(*) FROM ${kb}.ingest_failures WHERE failed_at >= current_timestamp() - INTERVAL 24 HOURS)
            AS failures_24h
   FROM (SELECT * FROM ${kb}.sync_runs ORDER BY finished_at DESC LIMIT 1) r;
