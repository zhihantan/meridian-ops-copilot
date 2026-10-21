"""Generate the Meridian ops dashboard for each bundle target (T27): an AI/BI dashboard as code.

One definition, written per target with that target's fully qualified names (development mode prefixes schema
names) to dashboards/meridian_ops.<target>.lvdash.json, which the bundle deploys (resources/dashboards.yml). A page
is included only where its tables exist in the target: the copilot's traces are in prod only. Viewers query with
their own permissions (embed_credentials false), so masks and the market row filter apply in the dashboard too.

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


def text(lines: list[str], x: int, y: int, w: int = 6, h: int = 2) -> dict:
    # The dashboard concatenates lines, so each one but the last ends with a newline (else the heading swallows the text).
    return {"widget": {"name": wid("text", *lines),
                       "multilineTextboxSpec": {"lines": [f"{line}\n" for line in lines[:-1]] + lines[-1:]}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def sgt(column: str, alias: str) -> str:
    return f"date_format(from_utc_timestamp({column}, 'Asia/Singapore'), 'dd MMM HH:mm') AS {alias}"


def callers(agent: str) -> str:
    """Persona label per principal from the membership mirrors, so no principal ID or user name is in the repo."""
    return f"""WITH roles AS (SELECT principal, 'Eli (admin)' AS caller, 0 AS rank FROM {agent}.approvers
               UNION ALL SELECT principal, 'Ben (finance)', 1 FROM {agent}.tier_members WHERE tier = 'finance'
               UNION ALL SELECT principal, 'Ava (support)', 2 FROM {agent}.tier_members WHERE tier = 'general'),
          callers AS (SELECT principal, min_by(caller, rank) AS caller FROM roles GROUP BY principal)"""


def build(t, w: WorkspaceClient) -> dict:
    c, s = t.catalog, t.schemas
    existing = {f"{r[0]}.{r[1]}" for r in sql(w, f"""SELECT table_schema, table_name FROM {c}.information_schema.tables
                                                    WHERE table_schema IN ('{s['obs']}', '{s['kb']}', '{s['agent']}',
                                                                           '{s['gold']}', '{s['silver']}', '{s['gov']}',
                                                                           '{s['quarantine']}')""")}

    def has(schema: str, name: str) -> bool:
        return f"{s[schema]}.{name}" in existing

    datasets, pages = [], []

    def dataset(name: str, title: str, query: str) -> str:
        datasets.append({"name": name, "displayName": title, "queryLines": [" ".join(query.split())]})
        return name

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
    if has("obs", "evidence"):
        o = f"{c}.{s['obs']}"
        dataset("scorecard", "POC scorecard", f"SELECT req_id, requirement, tasks, status, headline, evidence FROM {o}.evidence ORDER BY req_id")
        dataset("score_counts", "Scorecard counts", f"SELECT count_if(status = 'PASS') AS pass, count_if(status = 'PARTIAL') AS partial, count_if(status NOT IN ('PASS', 'PARTIAL')) AS other, count(*) AS requirements FROM {o}.evidence")
        pages.insert(0, {"name": wid("page", "scorecard"), "displayName": "POC scorecard", "layout": [
            text(["## POC scorecard", "Each requirement, the tasks that answer it, and the status of their evidence (docs/evidence/INDEX.md)."], 0, 0),
            counter("score_counts", "requirements", "Requirements", 0, 2),
            counter("score_counts", "pass", "Evidenced (PASS)", 2, 2),
            counter("score_counts", "partial", "Partly evidenced", 4, 2),
            table("scorecard", "Requirement, tasks, status and evidence", ["req_id", "requirement", "tasks", "status", "headline", "evidence"], 0, 5, 6, 12)]})
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
