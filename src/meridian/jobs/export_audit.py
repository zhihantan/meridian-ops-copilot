"""Daily audit export (T21): knowledge and workflow provenance as dated CSV files on the exports volume.

Writes /Volumes/<catalog>/<obs>/exports/audit/<date>/:
  kb_changes.csv            per knowledge document: version, last sync, last editor, time and reason (obs.v_kb_changes)
  audit_log.csv             kb.audit_log entries in the window: who changed knowledge or workflows, when and why
  corrections.csv           corrections and their decisions
  violations.csv            refused workflow actions (agent.violations)
  history_docs.csv          Delta table history of kb.docs
  history_corrections.csv   Delta table history of kb.corrections
  manifest.json             row counts and the run
A table that does not exist yet in this target is listed in the manifest as skipped.

    export_audit.py --catalog C --bronze-schema S [--date YYYY-MM-DD] [--days 7]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import json
from datetime import UTC, datetime

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser
from meridian.jobs.export_logs import write

HISTORY = "SELECT version, timestamp, userName, operation, to_json(operationParameters) AS parameters, " \
          "to_json(operationMetrics) AS metrics FROM (DESCRIBE HISTORY {table}) WHERE timestamp >= {since}"


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--date", default="", help="folder date (default: today, UTC)")
    p.add_argument("--days", type=int, default=7, help="window for the logs and histories")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    kb, agent, obs = (f"{n.catalog}.{n.schema(s)}" for s in ("kb", "agent", "obs"))
    since = f"current_timestamp() - INTERVAL {args.days} DAYS"
    exports = {
        "kb_changes.csv": (f"{obs}.v_kb_changes", f"SELECT * FROM {obs}.v_kb_changes ORDER BY doc_id"),
        "audit_log.csv": (f"{kb}.audit_log", f"SELECT * FROM {kb}.audit_log WHERE ts >= {since} ORDER BY ts"),
        "corrections.csv": (f"{kb}.corrections", f"SELECT * FROM {kb}.corrections ORDER BY submitted_at"),
        "violations.csv": (f"{agent}.violations", f"SELECT * FROM {agent}.violations WHERE at >= {since} ORDER BY at"),
        "history_docs.csv": (f"{kb}.docs", HISTORY.format(table=f"{kb}.docs", since=since)),
        "history_corrections.csv": (f"{kb}.corrections", HISTORY.format(table=f"{kb}.corrections", since=since)),
    }
    day = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    folder = Path(f"/Volumes/{n.catalog}/{n.schema('obs')}/exports/audit/{day}")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"generated_at": datetime.now(UTC).isoformat(), "run_id": args.run_id, "catalog": n.catalog,
                "window_days": args.days, "files": {}, "skipped": {}}
    for name, (table, query) in exports.items():
        if not spark.catalog.tableExists(table):
            manifest["skipped"][name] = f"{table} does not exist yet"
            continue
        rows = [r.asDict(recursive=True) for r in spark.sql(query).collect()]
        write(folder / name, rows)
        manifest["files"][name] = len(rows)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"audit export {folder}: {manifest['files']}; skipped {list(manifest['skipped'])}")


if __name__ == "__main__":
    main()
