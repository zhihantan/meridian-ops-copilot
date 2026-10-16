-- Copilot observability (T27, BUILD views over MLflow's Unity Catalog trace tables). Applied by
-- scripts/setup_traces.py where the copilot's traces land, with ${agent} (catalog.schema) and ${prefix} (the trace
-- table prefix) filled in. Spans arrive within seconds of a call ending (observed 2026-10-17).

-- One row per copilot invocation: who asked, with which tiers, how long it took, and what it used.
CREATE OR REPLACE VIEW ${agent}.v_copilot_runs
COMMENT 'BUILD: one row per copilot invocation: caller, tiers, duration, model and tool calls, tokens including cache'
AS SELECT m.trace_id, m.tags['user'] AS principal, m.tags['tiers'] AS tiers, m.tags['invocation'] AS invocation_id,
          min(s.time) AS started_at,
          round((max(s.end_time_unix_nano) - min(s.start_time_unix_nano)) / 1e6) AS duration_ms,
          count_if(s.name = 'AsyncMessages.create') AS model_calls,
          count_if(s.attributes:['mlflow.spanType']::string IN ('TOOL', 'RETRIEVER')) AS tool_calls,
          sum(s.attributes:['mlflow.spanOutputs'].usage.input_tokens::bigint) AS input_tokens,
          sum(s.attributes:['mlflow.spanOutputs'].usage.output_tokens::bigint) AS output_tokens,
          sum(s.attributes:['mlflow.spanOutputs'].usage.cache_read_input_tokens::bigint) AS cache_read_tokens,
          sum(s.attributes:['mlflow.spanOutputs'].usage.cache_creation_input_tokens::bigint) AS cache_write_tokens
   FROM ${agent}.${prefix}_trace_metadata m JOIN ${agent}.${prefix}_otel_spans s ON s.trace_id = m.trace_id
   GROUP BY m.trace_id, m.tags['user'], m.tags['tiers'], m.tags['invocation'];

-- The slowest tools and steps.
CREATE OR REPLACE VIEW ${agent}.v_copilot_tool_latency
COMMENT 'BUILD: per tool, step and model call: calls, errors, median, 95th percentile and slowest duration'
AS SELECT name AS tool, attributes:['mlflow.spanType']::string AS span_type, count(*) AS calls,
          count_if(status.code = 'STATUS_CODE_ERROR') AS errors,
          round(percentile_approx((end_time_unix_nano - start_time_unix_nano) / 1e6, 0.5)) AS p50_ms,
          round(percentile_approx((end_time_unix_nano - start_time_unix_nano) / 1e6, 0.95)) AS p95_ms,
          round(max((end_time_unix_nano - start_time_unix_nano) / 1e6)) AS max_ms
   FROM ${agent}.${prefix}_otel_spans
   WHERE attributes:['mlflow.spanType']::string IN ('TOOL', 'RETRIEVER', 'CHAT_MODEL')
   GROUP BY 1, 2;

-- Everything that was refused or denied, wherever it was stopped.
CREATE OR REPLACE VIEW ${agent}.v_copilot_denials
COMMENT 'BUILD: refusals and denials: step guard and procedures, index refusals, model safeguard refusals, span errors'
AS SELECT s.time AS at, m.tags['user'] AS principal, s.name AS what,
          CASE WHEN s.attributes:refused::boolean THEN 'step guard or procedure refused'
               WHEN s.attributes:tiers_refused_by_index IS NOT NULL THEN 'index refused a tier'
               WHEN s.attributes:model_refusal IS NOT NULL THEN 'model safeguard refused'
               ELSE 'error' END AS kind,
          coalesce(s.attributes:['mlflow.spanOutputs'].refused::string, s.attributes:tiers_refused_by_index::string,
                   s.attributes:model_refusal::string, s.status.message) AS detail
   FROM ${agent}.${prefix}_otel_spans s JOIN ${agent}.${prefix}_trace_metadata m ON m.trace_id = s.trace_id
   WHERE s.attributes:refused::boolean OR s.attributes:tiers_refused_by_index IS NOT NULL
      OR s.attributes:model_refusal IS NOT NULL OR s.status.code = 'STATUS_CODE_ERROR'
   UNION ALL
   SELECT at, caller, attempted, 'workflow violation', reason FROM ${agent}.violations;
