"""Generate the Meridian ops dashboard for each bundle target (T27): an AI/BI dashboard as code.

One definition, written per target with that target's fully qualified names (development mode prefixes schema
names) to dashboards/meridian_ops.<target>.lvdash.json, which the bundle deploys (resources/dashboards.yml). Pages:
- Data products: what the pipeline built, its quality, the PII it protects, lineage and who reads it.
- Jobs and pipeline: triggers, runs, rows written, expectations and serverless cost.
- Pipeline health, Knowledge, and Copilot.
A page is included only where its tables exist in the target: the copilot's traces are in prod only. Viewers query
with their own permissions (embed_credentials false), so masks and the market row filter apply in the dashboard too.

    uv run --group dbx python scripts/gen_dashboard.py --target dev --target staging --target prod
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]


def wid(*parts: str) -> str:
    return hashlib.md5(":".join(parts).encode()).hexdigest()[:8]  # a stable name, not a security use


def table(ds: str, title: str, fields: list[str], x: int, y: int, w: int = 6, h: int = 7) -> dict:
    # Table spec version 2, the shape the dashboard UI writes. Version 1 needs about 20 settings per column, and
    # without them each table renders as "Invalid widget definition is imported".
    return {"widget": {"name": wid("table", ds, title),
                       "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": True,
                                    "fields": [{"name": f, "expression": f"`{f}`"} for f in fields]}}],
                       "spec": {"version": 2, "widgetType": "table",
                                "encodings": {"columns": [{"fieldName": f} for f in fields]},
                                "data": {"queryName": "main_query"},
                                "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def counter(ds: str, field: str, title: str, x: int, y: int, w: int = 2, h: int = 3) -> dict:
    return {"widget": {"name": wid("counter", ds, field),
                       "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": True,
                                    "fields": [{"name": field, "expression": f"`{field}`"}]}}],
                       "spec": {"version": 2, "widgetType": "counter",
                                "encodings": {"value": {"fieldName": field, "displayName": title}},
                                "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def bar(ds: str, x_field: str, y_field: str, title: str, x: int, y: int, w: int = 3, h: int = 6) -> dict:
    return {"widget": {"name": wid("bar", ds, x_field, y_field),
                       "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": True,
                                    "fields": [{"name": f, "expression": f"`{f}`"} for f in (x_field, y_field)]}}],
                       "spec": {"version": 3, "widgetType": "bar",
                                "encodings": {"x": {"fieldName": x_field, "scale": {"type": "categorical"},
                                                    "displayName": x_field},
                                              "y": {"fieldName": y_field, "scale": {"type": "quantitative"},
                                                    "displayName": y_field}},
                                "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def trend(kind: str, ds: str, day: str, value: str, series: str, title: str, x: int, y: int, w: int = 6,
          h: int = 6, agg: str = "SUM") -> dict:
    """A line or stacked bar over days, one series per value of `series`: the aggregated shape the dashboard UI writes."""
    xf, yf = f"daily({day})", f"{agg.lower()}({value})"
    fields = [{"name": xf, "expression": f'DATE_TRUNC("DAY", `{day}`)'}, {"name": series, "expression": f"`{series}`"},
              {"name": yf, "expression": f"{agg}(`{value}`)"}]
    return {"widget": {"name": wid(kind, ds, day, value, series),
                       "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": False, "fields": fields}}],
                       "spec": {"version": 3, "widgetType": kind,
                                "encodings": {"x": {"fieldName": xf, "scale": {"type": "temporal"}, "displayName": day},
                                              "y": {"fieldName": yf, "scale": {"type": "quantitative"}, "displayName": value},
                                              "color": {"fieldName": series, "scale": {"type": "categorical"},
                                                        "displayName": series}},
                                "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def text(lines: list[str], x: int, y: int, w: int = 6, h: int = 2) -> dict:
    # The dashboard concatenates lines, so each one but the last ends with a newline (else the heading swallows the text).
    return {"widget": {"name": wid("text", *lines),
                       "multilineTextboxSpec": {"lines": [f"{line}\n" for line in lines[:-1]] + lines[-1:]}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def sgt(column: str, alias: str) -> str:
    return f"date_format(from_utc_timestamp({column}, 'Asia/Singapore'), 'dd MMM HH:mm') AS {alias}"


TRIGGER = """CASE {col} WHEN 'CRON' THEN 'schedule' WHEN 'PERIODIC' THEN 'schedule' WHEN 'FILE_ARRIVAL' THEN 'file arrival'
             WHEN 'TABLE' THEN 'table update' WHEN 'ONETIME' THEN 'manual or another job' ELSE lower({col}) END"""
PRICE = """LEFT JOIN system.billing.list_prices p ON p.sku_name = u.sku_name AND p.cloud = u.cloud AND p.currency_code = 'USD'
           AND u.usage_start_time >= p.price_start_time AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)"""
LATEST_JOBS = """SELECT job_id, name, tags, delete_time FROM system.lakeflow.jobs
                 QUALIFY row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) = 1"""
LATEST_PIPES = """SELECT pipeline_id, name FROM system.lakeflow.pipelines
                  QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1"""


def data_products(t, tables: list[tuple[str, str]], dataset) -> dict:
    """What the pipeline built: scale, quality, governance, lineage and use of the tables, bronze to gold."""
    c, s = t.catalog, t.schemas
    layer_of = {s[k]: k for k in ("bronze", "silver", "gold", "quarantine")}
    medallion = "', '".join(layer_of)
    dataset("product_counts", "Data product counts", f"""SELECT
        (SELECT count(*) FROM {c}.{s['silver']}.payments) AS payments,
        (SELECT count(*) FROM {c}.{s['quarantine']}.payments) AS quarantined,
        (SELECT count(DISTINCT concat_ws('.', schema_name, table_name, column_name)) FROM {c}.information_schema.column_tags
         WHERE tag_name LIKE 'class.%') AS protected_columns,
        (SELECT count(*) FROM {c}.information_schema.tables WHERE table_schema IN ('{medallion}') AND table_name NOT LIKE '\\\\_\\\\_%') AS tables,
        (SELECT count(*) FROM {c}.information_schema.tables WHERE table_schema = '{s['gold']}' AND table_name NOT LIKE '\\\\_\\\\_%') AS gold_tables,
        (SELECT count_if(status = 'degraded') FROM {c}.{s['gold']}.acquirer_status) AS degraded""")
    dataset("failure_trend", "Daily failure rate by acquirer", f"SELECT payment_date, acquirer_id, round(100 * failure_rate, 2) AS failure_pct FROM {c}.{s['gold']}.payment_failure_daily")
    dataset("daily_payments", "Payments per day by market", f"SELECT to_date(from_utc_timestamp(created_at, 'Asia/Singapore')) AS day, country, count(*) AS payments FROM {c}.{s['silver']}.payments GROUP BY ALL")
    dataset("quarantine_rules", "Quarantine by rule", f"SELECT rule, count(*) AS quarantined_rows FROM {c}.{s['quarantine']}.payments LATERAL VIEW explode(_failed_rules) r AS rule GROUP BY rule ORDER BY quarantined_rows DESC")
    counts = " UNION ALL ".join(f"SELECT '{layer_of[schema]}' AS layer, '{schema}' AS schema_name, '{name}' AS table_name, count(*) AS row_count FROM {c}.{schema}.{name}"
                                for schema, name in tables)
    dataset("assets", "Data assets", f"""WITH counts AS ({counts}),
        tagged AS (SELECT schema_name, table_name, count(DISTINCT column_name) AS protected_columns FROM {c}.information_schema.column_tags
                   WHERE tag_name LIKE 'class.%' GROUP BY ALL)
        SELECT n.layer, n.table_name, lower(replace(t.table_type, '_', ' ')) AS kind, n.row_count, coalesce(g.protected_columns, 0) AS protected_columns,
               {sgt('t.last_altered', 'last_changed_sgt')}, t.comment AS description
        FROM counts n JOIN {c}.information_schema.tables t ON t.table_schema = n.schema_name AND t.table_name = n.table_name
        LEFT JOIN tagged g ON g.schema_name = n.schema_name AND g.table_name = n.table_name
        ORDER BY CASE n.layer WHEN 'bronze' THEN 1 WHEN 'silver' THEN 2 WHEN 'gold' THEN 3 ELSE 4 END, n.table_name""")
    dataset("gold_lineage", "Where gold comes from", f"""WITH jobs AS ({LATEST_JOBS}), pipes AS ({LATEST_PIPES})
        SELECT l.target_table_name AS gold_table, l.source_table_full_name AS built_from, coalesce(j.name, p.name, lower(l.entity_type)) AS built_by
        FROM system.access.table_lineage l LEFT JOIN jobs j ON l.entity_type = 'JOB' AND l.entity_id = j.job_id
        LEFT JOIN pipes p ON l.entity_type = 'PIPELINE' AND l.entity_id = p.pipeline_id
        WHERE l.target_table_catalog = '{c}' AND l.target_table_schema = '{s['gold']}' AND l.source_table_full_name IS NOT NULL
          AND l.event_date >= current_date() - INTERVAL 30 DAYS
        GROUP BY ALL ORDER BY gold_table, built_from""")
    dataset("consumers", "Who reads the data", f"""SELECT CASE coalesce(entity_type, 'SQL') WHEN 'JOB' THEN 'jobs' WHEN 'PIPELINE' THEN 'pipelines'
            WHEN 'DASHBOARD_V3' THEN 'dashboards' WHEN 'SQL' THEN 'SQL and notebooks' ELSE lower(entity_type) END AS consumer,
            count(DISTINCT coalesce(entity_id, created_by)) AS consumers, count(*) AS read_events
        FROM system.access.table_lineage WHERE source_table_catalog = '{c}' AND event_date >= current_date() - INTERVAL 14 DAYS
        GROUP BY 1 ORDER BY read_events DESC""")
    return {"name": wid("page", "products"), "displayName": "Data products", "layout": [
        text(["## Data products", "What the pipeline built, bronze to gold: its scale and quality, the personal data it protects, where each gold table comes from, and who reads it. Native Unity Catalog and Lakeflow; lineage from system tables."], 0, 0),
        counter("product_counts", "payments", "Payments in silver", 0, 2),
        counter("product_counts", "quarantined", "Bad rows quarantined before silver", 2, 2),
        counter("product_counts", "protected_columns", "PII columns protected by tags", 4, 2),
        counter("product_counts", "tables", "Tables, bronze to gold", 0, 5),
        counter("product_counts", "gold_tables", "Gold data products", 2, 5),
        counter("product_counts", "degraded", "Acquirers degraded now", 4, 5),
        trend("line", "failure_trend", "payment_date", "failure_pct", "acquirer_id", "Daily failure rate by acquirer, % (gold): the acq_7 spike is the incident", 0, 8, agg="AVG"),
        trend("bar", "daily_payments", "day", "payments", "country", "Payments per day by market (silver; your row filter applies)", 0, 14, 3, 6),
        bar("quarantine_rules", "rule", "quarantined_rows", "Rows stopped by quarantine, by rule", 3, 14, 3, 6),
        table("assets", "Data assets: every table the pipeline and jobs maintain", ["layer", "table_name", "kind", "row_count", "protected_columns", "last_changed_sgt", "description"], 0, 20, 6, 8),
        table("gold_lineage", "Where each gold table comes from (lineage)", ["gold_table", "built_from", "built_by"], 0, 28, 3, 6),
        table("consumers", "Who reads Meridian data, last 14 days (lineage)", ["consumer", "consumers", "read_events"], 3, 28, 3, 6)]}


def jobs_and_pipeline(t, dataset) -> dict:
    """How the data is produced: triggers, runs and reliability, rows written, expectations, and serverless cost."""
    o = f"{t.catalog}.{t.schemas['obs']}"
    current = f"current AS (SELECT job_id FROM ({LATEST_JOBS}) WHERE tags['project'] = 'meridian-poc' AND tags['target'] = '{t.target}' AND delete_time IS NULL)"
    recent = "started_at >= current_timestamp() - INTERVAL 14 DAYS"
    dataset("job_counts", "Job counts", f"""WITH {current} SELECT (SELECT count(*) FROM current) AS jobs,
        count(*) AS runs, round(100 * count_if(result_state = 'SUCCEEDED') / count(*), 1) AS succeeded_pct
        FROM {o}.v_job_runs WHERE {recent} AND result_state IS NOT NULL""")
    dataset("runs_per_day", "Job runs per day", f"SELECT to_date(from_utc_timestamp(started_at, 'Asia/Singapore')) AS day, lower(result_state) AS result, count(*) AS runs FROM {o}.v_job_runs WHERE {recent} AND result_state IS NOT NULL GROUP BY ALL")
    dataset("jobs", "Jobs", f"""WITH {current} SELECT r.job_name, concat_ws(', ', sort_array(collect_set({TRIGGER.format(col='r.trigger_type')}))) AS triggers,
        count(*) AS runs, round(100 * count_if(r.result_state = 'SUCCEEDED') / count(*), 1) AS succeeded_pct, round(percentile(r.duration_s, 0.5)) AS median_seconds,
        {sgt('max(r.started_at)', 'last_run_sgt')}, lower(max_by(r.result_state, r.started_at)) AS last_result
        FROM {o}.v_job_runs r JOIN current USING (job_id) WHERE r.{recent} GROUP BY r.job_name ORDER BY runs DESC""")
    flows = f"{o}.pipeline_event_log WHERE event_type = 'flow_progress' AND details:flow_progress.metrics.num_output_rows IS NOT NULL"
    dataset("pipeline_counts", "Pipeline counts", f"""SELECT (SELECT count(DISTINCT origin.update_id) FROM {o}.pipeline_event_log WHERE timestamp >= current_timestamp() - INTERVAL 14 DAYS) AS updates,
        (SELECT sum(CAST(details:flow_progress.metrics.num_output_rows AS BIGINT)) FROM {flows}) AS rows_written,
        (SELECT round(sum(u.usage_quantity * p.pricing.default), 2) FROM system.billing.usage u {PRICE}
         WHERE u.custom_tags['project'] = 'meridian-poc' AND u.custom_tags['target'] = '{t.target}' AND u.usage_date >= current_date() - INTERVAL 14 DAYS) AS cost_usd""")
    dataset("rows_written", "Rows written per table", f"""SELECT origin.flow_name AS table_name, sum(CAST(details:flow_progress.metrics.num_output_rows AS BIGINT)) AS rows_written,
        count(DISTINCT origin.update_id) AS updates, {sgt('max(timestamp)', 'last_written_sgt')} FROM {flows} GROUP BY 1 ORDER BY rows_written DESC""")
    dataset("expectations", "Expectations", f"""SELECT expectation, sum(passed_records) + sum(failed_records) AS rows_checked, sum(failed_records) AS rows_failed,
        round(100 * sum(failed_records) / (sum(passed_records) + sum(failed_records)), 2) AS failed_pct FROM {o}.v_expectation_metrics GROUP BY expectation ORDER BY rows_failed DESC""")
    dataset("cost_by_job", "Cost per day by job", f"""WITH names AS ({LATEST_JOBS})
        SELECT u.usage_date AS day, coalesce(n.name, lower(u.billing_origin_product)) AS job, round(sum(u.usage_quantity * p.pricing.default), 2) AS usd
        FROM system.billing.usage u {PRICE} LEFT JOIN names n ON n.job_id = u.usage_metadata.job_id
        WHERE u.custom_tags['project'] = 'meridian-poc' AND u.custom_tags['target'] = '{t.target}' AND u.usage_date >= current_date() - INTERVAL 14 DAYS
        GROUP BY ALL""")
    return {"name": wid("page", "jobs"), "displayName": "Jobs and pipeline", "layout": [
        text(["## Jobs and pipeline", "How the data is produced: what triggers each job, how reliably it runs, what the pipeline wrote and checked, and what it cost. Native Lakeflow Jobs and pipelines; from system tables, which lag by minutes, and billing by hours."], 0, 0),
        counter("job_counts", "jobs", "Jobs in this environment", 0, 2),
        counter("job_counts", "runs", "Job runs, last 14 days", 2, 2),
        counter("job_counts", "succeeded_pct", "Runs that succeeded, %", 4, 2),
        trend("bar", "runs_per_day", "day", "runs", "result", "Job runs per day, by result", 0, 5),
        table("jobs", "Jobs: what triggers them and how they run, last 14 days", ["job_name", "triggers", "runs", "succeeded_pct", "median_seconds", "last_run_sgt", "last_result"], 0, 11, 6, 7),
        counter("pipeline_counts", "updates", "Pipeline updates, last 14 days", 0, 18),
        counter("pipeline_counts", "rows_written", "Rows written by the pipeline", 2, 18),
        counter("pipeline_counts", "cost_usd", "Serverless cost, last 14 days (USD, list price)", 4, 18),
        table("rows_written", "Pipeline: rows written per table", ["table_name", "rows_written", "updates", "last_written_sgt"], 0, 21, 3, 7),
        table("expectations", "Expectations: rows checked and failed per rule", ["expectation", "rows_checked", "rows_failed", "failed_pct"], 3, 21, 3, 7),
        trend("bar", "cost_by_job", "day", "usd", "job", "Serverless cost per day by job (USD at list price; usage tagged project=meridian-poc)", 0, 28)]}


def callers(agent: str) -> str:
    """Persona label per principal from the membership mirrors, so no principal ID or user name is in the repo."""
    return f"""WITH roles AS (SELECT principal, 'Eli (admin)' AS caller, 0 AS rank FROM {agent}.approvers
               UNION ALL SELECT principal, 'Ben (finance)', 1 FROM {agent}.tier_members WHERE tier = 'finance'
               UNION ALL SELECT principal, 'Ava (support)', 2 FROM {agent}.tier_members WHERE tier = 'general'),
          callers AS (SELECT principal, min_by(caller, rank) AS caller FROM roles GROUP BY principal)"""


def build(t, w: WorkspaceClient) -> dict:
    c, s = t.catalog, t.schemas
    rows = sql(w, f"""SELECT table_schema, table_name FROM {c}.information_schema.tables
                      WHERE table_schema IN ('{s['obs']}', '{s['kb']}', '{s['agent']}', '{s['gold']}', '{s['silver']}',
                                             '{s['gov']}', '{s['quarantine']}', '{s['bronze']}') ORDER BY 1, 2""")
    existing = {f"{r[0]}.{r[1]}" for r in rows}
    # The pipeline's own __materialization tables are internal, not data products.
    medallion = [(r[0], r[1]) for r in rows if r[0] in {s[k] for k in ("bronze", "silver", "gold", "quarantine")}
                 and not r[1].startswith("__")]

    def has(schema: str, name: str) -> bool:
        return f"{s[schema]}.{name}" in existing

    datasets, pages = [], []

    def dataset(name: str, title: str, query: str) -> str:
        datasets.append({"name": name, "displayName": title, "queryLines": [" ".join(query.split())]})
        return name

    if all(has(*x) for x in (("silver", "payments"), ("quarantine", "payments"), ("gold", "acquirer_status"),
                             ("gold", "payment_failure_daily"))):
        pages.append(data_products(t, medallion, dataset))
    if all(has("obs", x) for x in ("v_job_runs", "pipeline_event_log", "v_expectation_metrics")):
        pages.append(jobs_and_pipeline(t, dataset))

    if has("obs", "v_pipeline_health") and has("gold", "acquirer_status"):
        o, g, q = f"{c}.{s['obs']}", f"{c}.{s['gov']}", f"{c}.{s['quarantine']}"
        issue_sources = [("obs", "v_job_runs"), ("obs", "v_task_runs"), ("obs", "v_pipeline_events"), ("obs", "drift_events"),
                         ("obs", "freshness_events"), ("gov", "pii_coverage"), ("quarantine", "payments")]
        if all(has(*src) for src in issue_sources):
            # Problems only, over 14 days, so an incident stays on the page for a later walkthrough; successful runs
            # (most of them the 10-minute knowledge sweep) are left out.
            dataset("health", "Issues, last 14 days", f"""SELECT {sgt('at', 'at_sgt')}, source, name, status, detail FROM (
                SELECT ended_at AS at, 'job run' AS source, job_name AS name, result_state AS status, termination_code AS detail
                FROM {o}.v_job_runs WHERE ended_at >= current_timestamp() - INTERVAL 14 DAYS AND result_state <> 'SUCCEEDED'
                UNION ALL SELECT ended_at, 'task run', concat(job_name, '.', task_key), result_state, termination_code
                FROM {o}.v_task_runs WHERE ended_at >= current_timestamp() - INTERVAL 14 DAYS AND result_state NOT IN ('SUCCEEDED', 'EXCLUDED', 'SKIPPED')
                UNION ALL SELECT timestamp, 'pipeline', coalesce(flow_name, 'update'), level, coalesce(error_message, message)
                FROM {o}.v_pipeline_events WHERE timestamp >= current_timestamp() - INTERVAL 14 DAYS AND level IN ('ERROR', 'WARN')
                UNION ALL SELECT checked_at, concat('check: ', check_name), concat_ws('.', table_name, column_name), 'BREACH', message
                FROM (SELECT check_name, checked_at, table_name, column_name, message, breached FROM {o}.drift_events
                      UNION ALL SELECT check_name, checked_at, table_name, column_name, message, breached FROM {o}.freshness_events
                      UNION ALL SELECT check_name, checked_at, table_name, column_name, message, breached FROM {g}.pii_coverage)
                WHERE breached AND checked_at >= current_timestamp() - INTERVAL 14 DAYS
                UNION ALL SELECT max(_quarantined_at), 'quarantine', rule, 'QUARANTINED', concat(count(*), ' payment rows')
                FROM {q}.payments LATERAL VIEW explode(_failed_rules) r AS rule
                WHERE _quarantined_at >= current_timestamp() - INTERVAL 14 DAYS AND reprocessed_at IS NULL GROUP BY rule
                ) ORDER BY at DESC""")
            health = ("Issues in the last 14 days: failed runs and tasks, pipeline errors, check breaches, quarantine", "at_sgt")
        else:
            dataset("health", "Pipeline health, last 24h", f"SELECT at, source, name, status, detail FROM {o}.v_pipeline_health ORDER BY at DESC")
            health = ("Last 24 hours: jobs, pipeline errors, check breaches, quarantine", "at")
        dataset("acquirers", "Acquirer status", f"SELECT acquirer_id, status, round(100 * recent_failure_rate, 1) AS recent_failure_pct, round(100 * baseline_failure_rate, 1) AS baseline_failure_pct FROM {c}.{s['gold']}.acquirer_status ORDER BY status = 'degraded' DESC, recent_failure_rate DESC")
        dataset("markets", "Payments by market (your row filter applies)", f"SELECT country, count(*) AS payments FROM {c}.{s['silver']}.payments GROUP BY country ORDER BY payments DESC")
        pages.append({"name": wid("page", "pipeline"), "displayName": "Pipeline health", "layout": [
            text(["## Pipeline health", "Quality, freshness and failures from the observability views. BUILD views over native sources."], 0, 0),
            table("acquirers", "Acquirer status, degraded first (recent 6h vs 14-day baseline, %)", ["acquirer_id", "status", "recent_failure_pct", "baseline_failure_pct"], 0, 2, 3, 7),
            bar("markets", "country", "payments", "Payments by market (the market row filter applies per viewer)", 3, 2, 3, 7),
            table("health", health[0], [health[1], "source", "name", "status", "detail"], 0, 9, 6, 8)]})
    if has("kb", "sync_status"):
        dataset("kb_status", "Knowledge sync", f"SELECT last_run_at, live_docs_general, live_docs_finance, chunks_general, chunks_finance, failures_24h FROM {c}.{s['kb']}.sync_status")
        layout = [text(["## Knowledge", "kb_sync runs, document and chunk counts per tier, failures. BUILD."], 0, 0),
                  counter("kb_status", "live_docs_general", "General documents", 0, 2),
                  counter("kb_status", "live_docs_finance", "Finance documents", 2, 2),
                  counter("kb_status", "failures_24h", "Ingest failures, 24h", 4, 2)]
        if has("obs", "v_kb_changes"):
            dataset("kb_changes", "Knowledge changes", f"SELECT doc_id, source, tier, source_version, last_editor, {sgt('edited_at', 'edited_sgt')}, change FROM {c}.{s['obs']}.v_kb_changes WHERE deleted_at IS NULL ORDER BY edited_at DESC")
            layout.append(table("kb_changes", "Who changed each document, and when", ["doc_id", "source", "tier", "source_version", "last_editor", "edited_sgt", "change"], 0, 5, 6, 9))
        pages.append({"name": wid("page", "knowledge"), "displayName": "Knowledge", "layout": layout})
    if has("agent", "v_copilot_runs"):
        a = f"{c}.{s['agent']}"
        if has("agent", "approvers") and has("agent", "tier_members"):
            dataset("runs_by_user", "Copilot runs by caller", f"{callers(a)} SELECT coalesce(c.caller, 'other') AS caller, count(*) AS runs, round(avg(r.duration_ms) / 1000, 1) AS avg_seconds, sum(r.input_tokens) AS input_tokens, sum(r.cache_read_tokens) AS cache_read_tokens FROM {a}.v_copilot_runs r LEFT JOIN callers c ON c.principal = r.principal GROUP BY 1 ORDER BY runs DESC")
            dataset("denials", "Refusals and denials", f"{callers(a)} SELECT {sgt('d.at', 'at_sgt')}, coalesce(c.caller, 'other') AS caller, d.kind, d.what, d.detail FROM {a}.v_copilot_denials d LEFT JOIN callers c ON c.principal = d.principal ORDER BY d.at DESC")
            caller_field, denial_fields = "caller", ["at_sgt", "caller", "kind", "what", "detail"]
        else:
            dataset("runs_by_user", "Copilot runs by caller", f"SELECT principal, count(*) AS runs, round(avg(duration_ms) / 1000, 1) AS avg_seconds, sum(input_tokens) AS input_tokens, sum(cache_read_tokens) AS cache_read_tokens FROM {a}.v_copilot_runs GROUP BY principal ORDER BY runs DESC")
            dataset("denials", "Refusals and denials", f"SELECT at, kind, what, detail FROM {a}.v_copilot_denials ORDER BY at DESC")
            caller_field, denial_fields = "principal", ["at", "kind", "what", "detail"]
        dataset("latency", "Tool latency", f"SELECT tool, calls, errors, p50_ms, p95_ms, max_ms FROM {a}.v_copilot_tool_latency ORDER BY p95_ms DESC")
        dataset("cache", "Prompt cache", f"SELECT sum(input_tokens) AS uncached_input, sum(cache_read_tokens) AS cache_read, sum(cache_write_tokens) AS cache_write FROM {a}.v_copilot_runs")
        pages.append({"name": wid("page", "copilot"), "displayName": "Copilot", "layout": [
            text(["## Copilot", "From the copilot's traces in Unity Catalog. Every run is the caller's own. BUILD views."], 0, 0),
            counter("cache", "cache_read", "Tokens read from the prompt cache", 0, 2),
            counter("cache", "uncached_input", "Uncached input tokens", 2, 2),
            counter("cache", "cache_write", "Tokens written to the cache", 4, 2),
            bar("runs_by_user", caller_field, "runs", "Runs by caller", 0, 5, 3, 6),
            table("latency", "Slowest tools and steps (ms)", ["tool", "calls", "errors", "p50_ms", "p95_ms", "max_ms"], 3, 5, 3, 6),
            table("denials", "Refused and denied: guard, procedures, indexes, model safeguard", denial_fields, 0, 11, 6, 8)]})
    return {"datasets": datasets, "pages": pages}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", action="append", default=[], help="repeat for several targets")
    args = p.parse_args()
    w = WorkspaceClient()
    targets = args.target or ["dev"]
    for target in targets:  # the bundle reads every target's file to validate, so none may be missing
        placeholder = REPO / "dashboards" / f"meridian_ops.{target}.lvdash.json"
        placeholder.parent.mkdir(exist_ok=True)
        if not placeholder.exists():
            placeholder.write_text(json.dumps({"datasets": [], "pages": []}) + "\n")
    for target in targets:
        t = target_names(target)
        out = REPO / "dashboards" / f"meridian_ops.{target}.lvdash.json"
        dash = build(t, w)
        out.write_text(json.dumps(dash, indent=2) + "\n")
        print(f"{out.relative_to(REPO)}: pages {[p['displayName'] for p in dash['pages']]}")


if __name__ == "__main__":
    main()
