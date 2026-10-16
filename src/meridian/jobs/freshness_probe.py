"""Knowledge freshness probe (T14): how long a source create, edit and delete takes to reach the index.

Each run writes a canary document (kb/files/general/) and a canary Slack history page, then measures,
per phase, the time from the source write until kb.docs reflects it (ingested) and until the general
index does (indexed): visible after create, the new text after edit, gone after delete. In prod the
file-arrival trigger runs kb_sync; with --drive-sync (dev, where triggers are paused) the probe starts
kb_sync itself. Results go to eval.freshness_runs.

    freshness_probe.py --catalog C --bronze-schema S --kb-root /Volumes/.../raw/kb --sync-job-id J [--runs 5]
                       [--drive-sync true]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import io
import json
import time
import uuid
from datetime import UTC, datetime

from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser

POLL_S, TIMEOUT_S = 10, 1200


def slack_page(key: str, text: str) -> str:
    ts = f"{time.time():.6f}"
    return json.dumps({"ok": True, "channel": {"id": "C0OPSINC", "name": "ops-incidents"}, "has_more": False,
                       "messages": [{"type": "message", "user": "U05GUS", "text": text, "ts": ts, "msg_key": key}]})


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--kb-root", required=True)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--drive-sync", default="false", help="start kb_sync after each write (targets with paused triggers)")
    p.add_argument("--sync-job-id", type=int, required=True, help="the target's kb_sync job")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    w = WorkspaceClient()
    index = n.table("kb", "idx_general")
    results = n.table("eval", "freshness_runs")
    sync_job = args.sync_job_id if args.drive_sync == "true" else None

    def indexed(doc_id: str) -> str | None:
        res = w.vector_search_indexes.query_index(index_name=index, columns=["doc_id", "text"], query_text=doc_id,
                                                  num_results=3, filters_json=json.dumps({"doc_id": doc_id}))
        rows = (res.result.data_array or []) if res.result else []
        return rows[0][1] if rows else None

    def in_docs(doc_id: str) -> tuple[bool, str | None]:
        row = spark.sql(f"SELECT deleted_at IS NULL AS live, content_hash FROM {n.table('kb', 'docs')} "
                        f"WHERE doc_id = '{doc_id}'").first()
        return (bool(row["live"]), row["content_hash"]) if row else (False, None)

    def wait(checks: dict) -> dict:
        """checks: source -> (ingested?, indexed?). Poll all sources together; first time each turns true."""
        times = {source: [None, None] for source in checks}
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline and any(None in t for t in times.values()):
            for source, (done_ingest, done_index) in checks.items():
                if times[source][0] is None and done_ingest():
                    times[source][0] = time.time()
                if times[source][1] is None and done_index():
                    times[source][1] = time.time()
            if any(None in t for t in times.values()):
                time.sleep(POLL_S)
        return times

    rows = []
    for run in range(1, args.runs + 1):
        probe = uuid.uuid4().hex[:10].upper()
        targets = {
            "volume": (f"CANARY-{probe}", f"{args.kb_root}/files/general/CANARY-{probe}.md",
                       lambda v, pid=probe: f"# Canary {pid}\n\nCANARY-{pid} freshness probe version {v}.\n"),
            "slack": (f"SLACK-CANARY-{probe}-S", f"{args.kb_root}/slack/history/ops-incidents/canary-{probe}.json",
                      lambda v, pid=probe: slack_page(f"CANARY-{pid}-S", f"CANARY-{pid}-S freshness probe version {v}.")),
        }
        for phase in ("create", "edit", "delete"):
            before = {s: in_docs(doc_id)[1] for s, (doc_id, _, _) in targets.items()}
            t_source = time.time()
            for _, path, body in targets.values():
                if phase == "delete":
                    w.files.delete(path)
                else:
                    w.files.upload(path, io.BytesIO(body(1 if phase == "create" else 2).encode()), overwrite=True)
            if sync_job:
                w.jobs.run_now(job_id=sync_job)
            checks = {}
            for source, (doc_id, _, _) in targets.items():
                if phase == "create":
                    checks[source] = (lambda d=doc_id: in_docs(d)[0], lambda d=doc_id: indexed(d) is not None)
                elif phase == "edit":
                    checks[source] = (lambda d=doc_id, h=before[source]: in_docs(d)[1] not in (None, h),
                                      lambda d=doc_id: "version 2" in (indexed(d) or ""))
                else:
                    checks[source] = (lambda d=doc_id: not in_docs(d)[0], lambda d=doc_id: indexed(d) is None)
            for source, (t_ingest, t_index) in wait(checks).items():
                rows.append((datetime.now(UTC), args.run_id, run, probe, source, phase,
                             datetime.fromtimestamp(t_source, UTC),
                             datetime.fromtimestamp(t_ingest, UTC) if t_ingest else None,
                             datetime.fromtimestamp(t_index, UTC) if t_index else None,
                             round(t_ingest - t_source, 1) if t_ingest else None,
                             round(t_index - t_source, 1) if t_index else None))
                print(f"run {run} {source:<6} {phase:<6} ingested {rows[-1][9]}s indexed {rows[-1][10]}s")

    spark.createDataFrame(rows, "measured_at TIMESTAMP, job_run_id STRING, run INT, probe STRING, source STRING, "
                                "phase STRING, t_source TIMESTAMP, t_ingested TIMESTAMP, t_indexed TIMESTAMP, "
                                "seconds_to_ingest DOUBLE, seconds_to_index DOUBLE") \
        .write.mode("append").saveAsTable(results)
    for r in spark.sql(f"""SELECT source, phase, count(*) AS n, count(seconds_to_index) AS completed,
                                  percentile(seconds_to_index, 0.5) AS p50_s, percentile(seconds_to_index, 0.95) AS p95_s
                           FROM {results} WHERE job_run_id = '{args.run_id}' GROUP BY 1, 2 ORDER BY 1, 2""").collect():
        print(f"{r['source']:<6} {r['phase']:<6} n={r['n']} completed={r['completed']} p50={r['p50_s']}s p95={r['p95_s']}s")


if __name__ == "__main__":
    main()
