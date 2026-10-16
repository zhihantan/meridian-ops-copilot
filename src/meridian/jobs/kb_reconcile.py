"""Knowledge reconciliation (T15): source, kb.docs, chunk tables and indexes must hold the same documents.

Runs first in each kb_sync run, before anything is repaired. When the system is settled (no source file
changed since the last sync started, and no index sync running), every tier-mapped source document must
be live in kb.docs, have chunks in its tier's table, and appear in that tier's index. Differences are
silent drops (a row deleted by hand, an index that lost rows) and fail the task with the document IDs,
so the failure email names them. Results go to obs.kb_reconcile_events.

    kb_reconcile.py --catalog C --bronze-schema S
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser

TIERS = ("general", "finance")


def index_doc_ids(w: WorkspaceClient, index: str) -> tuple[set[str] | None, str]:
    """Documents in an index, by scanning it (small indexes). None when the index is missing or syncing."""
    try:
        status = w.vector_search_indexes.get_index(index).status
    except NotFound:
        return None, "no index"
    if not (status and status.ready) or "progress" in (status.message or "").lower():
        return None, "index not ready or syncing"
    ids, last = set(), None
    while True:
        page = w.vector_search_indexes.scan_index(index_name=index, num_results=1000, last_primary_key=last)
        rows = page.data or []
        for row in rows:
            ids.update(f.value.string_value for f in row.fields if f.key == "doc_id" and f.value)
        if not rows or not page.last_primary_key or page.last_primary_key == last:
            return ids, "ok"
        last = page.last_primary_key


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # Spark returns naive UTC timestamps


def main() -> None:
    args = parser(__doc__.splitlines()[0]).parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    w = WorkspaceClient()
    kb = f"{n.catalog}.{n.schema('kb')}"
    if not spark.catalog.tableExists(f"{kb}.sync_runs"):
        print("no kb_sync run yet; nothing to reconcile")
        return
    last_sync = spark.sql(f"SELECT max(started_at) AS t FROM {kb}.sync_runs").first()["t"]
    try:
        newest_file = spark.sql(f"SELECT max(file_modified_at) AS t FROM {kb}.v_source_docs").first()["t"]
    except Exception as exc:  # noqa: BLE001  the view predates this check; this run's sync recreates it
        print(f"source view not upgraded yet ({type(exc).__name__}); skipped")
        return
    if last_sync is None or (newest_file and newest_file >= last_sync):
        print(f"not settled: source changed at {newest_file}, after the last sync started at {last_sync}")
        return

    source = {r["doc_id"]: r["tier"] for r in spark.sql(
        f"SELECT doc_id, tier FROM {kb}.v_source_docs WHERE tier IN ('general', 'finance')").collect()}
    docs = {r["doc_id"] for r in spark.sql(f"SELECT doc_id FROM {kb}.docs WHERE deleted_at IS NULL").collect()}
    # Documents that failed to ingest are known (kb.ingest_failures says why), not silent drops.
    failed = {r["doc_id"] for r in spark.sql(f"SELECT DISTINCT doc_id FROM {kb}.ingest_failures "
                                             f"WHERE failed_at >= TIMESTAMP '{last_sync}'").collect()}
    problems: list[tuple[str, str, str]] = []  # (doc_id, where, message)
    for doc_id in sorted(set(source) - docs - failed):
        problems.append((doc_id, "kb.docs", "in the source but not live in kb.docs"))
    for doc_id in sorted(failed & set(source)):
        print(f"  {doc_id}: failed to ingest; see kb.ingest_failures")
    source = {d: t for d, t in source.items() if d not in failed}
    for doc_id in sorted(docs - set(source)):
        problems.append((doc_id, "kb.docs", "live in kb.docs but gone from the source"))
    for tier in TIERS:
        expected = {d for d, t in source.items() if t == tier}
        chunked = {r["doc_id"] for r in spark.sql(f"SELECT DISTINCT doc_id FROM {kb}.chunks_{tier}").collect()}
        for doc_id in sorted(expected - chunked):
            problems.append((doc_id, f"chunks_{tier}", "no chunks"))
        indexed, state = index_doc_ids(w, n.table("kb", f"idx_{tier}"))
        recent = (now_utc() - last_sync).total_seconds() < 600  # an index sync may still be running
        if indexed is None or (recent and indexed != chunked):
            print(f"idx_{tier}: {state if indexed is None else 'sync may be running'}; index not compared")
            continue
        for doc_id in sorted(chunked - indexed):
            problems.append((doc_id, f"idx_{tier}", "chunked but missing from the index"))

    now = datetime.now(UTC)
    rows = [(now, args.run_id, d, where, msg) for d, where, msg in problems] or [(now, args.run_id, None, None, "ok")]
    spark.createDataFrame(rows, "checked_at TIMESTAMP, run_id STRING, doc_id STRING, layer STRING, message STRING") \
        .write.mode("append").saveAsTable(n.table("obs", "kb_reconcile_events"))
    print(f"reconciled {len(source)} source documents: {len(problems)} problem(s)")
    for d, where, msg in problems:
        print(f"  {d} [{where}]: {msg}")
    if problems:
        raise SystemExit(f"knowledge reconciliation: {len(problems)} silent drop(s), first {problems[0][0]}")


if __name__ == "__main__":
    main()
