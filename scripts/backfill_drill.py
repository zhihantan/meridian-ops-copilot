"""Evidence for the bad-backfill drill (T06): root cause, blast radius and recovery. Read-only.

Collects, for one target: the silver.payments history entries written by the backfill job (DESCRIBE
HISTORY, which is immediate), the corrupted day's totals before the bad write and now (time travel), the
gold.acquirer_status versions, the table-update runs of the acquirer-status job, and the writes into
silver.payments that system.access.table_lineage has recorded so far (it lags, so run it again later).
The drill itself is bundle jobs and SQL; see docs/runbooks/bad_backfill.md.

    uv run --group dbx python scripts/backfill_drill.py --target prod [--out docs/evidence/T06/drill_prod.json]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]
SGT_DAY = "to_date(from_utc_timestamp(created_at, 'Asia/Singapore'))"


def person_free(identity: str | None) -> str | None:
    """Evidence is public: keep service principal IDs, replace user emails."""
    return "<user>" if identity and "@" in identity else identity


def job_ref(job_json: str | None) -> dict:
    """Job name, IDs and trigger from a history entry (workspace and owner IDs left out)."""
    job = json.loads(job_json) if job_json else {}
    return {k: job[k] for k in ("jobName", "jobId", "jobRunId", "triggerType") if k in job}


def rows_changed(metrics_json: str) -> str | None:
    metrics = json.loads(metrics_json or "{}")
    return metrics.get("numUpdatedRows") or metrics.get("numTargetRowsUpdated")


def history(w: WorkspaceClient, table: str, limit: int = 30) -> list[dict]:
    rows = sql(w, f"SELECT version, timestamp, userName, operation, operationParameters, job, operationMetrics "
                  f"FROM (DESCRIBE HISTORY {table} LIMIT {limit})")
    keys = ("version", "timestamp", "user", "operation", "parameters", "job", "metrics")
    return [dict(zip(keys, r)) for r in rows]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--backfill-job", default="meridian-backfill-fx-correction", help="job name suffix to look for")
    p.add_argument("--out")
    args = p.parse_args()
    w = WorkspaceClient()
    t = target_names(args.target)
    silver, status = t.table("silver", "payments"), t.table("gold", "acquirer_status")

    hist = history(w, silver)
    bad = [h for h in hist if h["operation"] in ("UPDATE", "MERGE", "DELETE") and args.backfill_job in (h["job"] or "")]
    result: dict = {"task": "T06 bad backfill drill", "target": args.target,
                    "collected_at": datetime.now(UTC).isoformat(), "silver": silver}

    # Root cause from the table's own history: immediate, names the job and run.
    result["bad_writes"] = [{"version": h["version"], "at": h["timestamp"], "operation": h["operation"],
                             "job": job_ref(h["job"]), "rows": rows_changed(h["metrics"])}
                            for h in bad]
    last = max(result["bad_writes"], key=lambda h: int(h["version"])) if bad else None
    recovered = [h for h in hist if last and int(h["version"]) > int(last["version"])
                 and h["operation"] == "DLT REFRESH"]
    result["recovery_writes"] = [{"version": h["version"], "at": h["timestamp"], "operation": h["operation"]}
                                 for h in recovered]

    # Blast radius: the corrupted day's totals before the latest bad write and now.
    if last:
        before = int(last["version"]) - 1
        totals = sql(w, f"""
            WITH b AS (SELECT {SGT_DAY} AS day, sum(amount) AS amount, count(*) AS n FROM {silver} VERSION AS OF {before} GROUP BY 1),
                 a AS (SELECT {SGT_DAY} AS day, sum(amount) AS amount, count(*) AS n FROM {silver} VERSION AS OF {last['version']} GROUP BY 1),
                 c AS (SELECT {SGT_DAY} AS day, sum(amount) AS amount, count(*) AS n FROM {silver} GROUP BY 1)
            SELECT b.day, b.n, round(b.amount, 2), round(a.amount, 2), c.n, round(c.amount, 2)
            FROM b JOIN a USING (day) JOIN c USING (day) WHERE round(a.amount, 2) <> round(b.amount, 2)""")
        result["corrupted_days"] = [{"day": r[0], "rows": r[1], "amount_before": r[2], "amount_after_bad_write": r[3],
                                     "rows_now": r[4], "amount_now": r[5], "recovered": r[5] == r[2] and r[4] == r[1]}
                                    for r in totals]

    # Propagation and mitigation on the ordinary Delta table.
    if w.tables.exists(status).table_exists:
        result["acquirer_status_versions"] = [
            {"version": h["version"], "at": h["timestamp"], "operation": h["operation"],
             "job": job_ref(h["job"]).get("jobName"), "run": job_ref(h["job"]).get("jobRunId"),
             "trigger": job_ref(h["job"]).get("triggerType"),
             "parameters": h["parameters"] if h["operation"] == "RESTORE" else None}
            for h in history(w, status, 10)]
        result["acquirer_status_now"] = sql(w, f"SELECT acquirer_id, baseline_daily_amount, run_id FROM {status} "
                                               "ORDER BY acquirer_id")

    # Lineage (system table, lags): every job and pipeline run that read or wrote silver.payments. DML into
    # a pipeline streaming table from a job is not recorded as a write edge (observed 2026-10-15), so the
    # backfill shows up through its read of silver.payments; the table history above names the write.
    result["lineage_touches"] = [dict(zip(("event_time", "direction", "entity_type", "job_or_pipeline", "entity_id",
                                           "entity_run_id", "other_table", "created_by"), [*r[:7], person_free(r[7])]))
                                 for r in sql(w, f"""
        WITH jobs AS (SELECT job_id, name FROM system.lakeflow.jobs
                      QUALIFY row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) = 1),
             pipes AS (SELECT pipeline_id, name FROM system.lakeflow.pipelines
                       QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1)
        SELECT max(l.event_time), IF(l.target_table_full_name = '{silver}', 'writes', 'reads'), l.entity_type,
               coalesce(j.name, p.name), l.entity_id, l.entity_run_id,
               IF(l.target_table_full_name = '{silver}', l.source_table_full_name, l.target_table_full_name),
               max(l.created_by)
        FROM system.access.table_lineage l
        LEFT JOIN jobs j ON l.entity_type = 'JOB' AND l.entity_id = j.job_id
        LEFT JOIN pipes p ON l.entity_type = 'PIPELINE' AND l.entity_id = p.pipeline_id
        WHERE (l.target_table_full_name = '{silver}' OR l.source_table_full_name = '{silver}')
          AND l.event_date >= current_date() - INTERVAL 7 DAYS AND l.entity_type IN ('JOB', 'PIPELINE')
        GROUP BY ALL ORDER BY 1 DESC LIMIT 25""")]
    result["lineage_names_bad_run"] = any(
        args.backfill_job in (r["job_or_pipeline"] or "") and r["entity_run_id"] == last["job"].get("jobRunId")
        for r in result["lineage_touches"]) if last else False

    checks = {"bad write found in history": bool(bad),
              "corrupted day recovered": bool(result.get("corrupted_days"))
              and all(d["recovered"] for d in result["corrupted_days"]),
              "acquirer_status restored": any(v["operation"] == "RESTORE"
                                              for v in result.get("acquirer_status_versions", []))}
    result["checks"] = checks
    result["status"] = "PASS" if all(checks.values()) else "OPEN"
    text = json.dumps(result, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
