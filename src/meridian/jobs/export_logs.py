"""Daily log export (T06b): the last 24h of health, job runs and pipeline events as dated files.

Writes to the exports volume, /Volumes/<catalog>/<obs>/exports/logs/<date>/, which external monitoring
can pick up. A managed volume sits on the workspace's own cloud storage; an external volume on an S3
prefix takes the same code with a different path.

    export_logs.py --catalog C --bronze-schema S [--date YYYY-MM-DD]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import csv
import json
from datetime import UTC, datetime

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser

EXPORTS = {
    "pipeline_health.jsonl": "SELECT * FROM {obs}.v_pipeline_health ORDER BY at",
    "job_runs.csv": "SELECT * FROM {obs}.v_job_runs WHERE ended_at >= current_timestamp() - INTERVAL 24 HOURS "
                    "ORDER BY started_at",
    "pipeline_events.jsonl": "SELECT timestamp, event_type, level, update_id, flow_name, message, error_message "
                             "FROM {obs}.v_pipeline_events WHERE timestamp >= current_timestamp() - INTERVAL 24 HOURS "
                             "ORDER BY timestamp",
}


def write(path: Path, rows: list[dict]) -> None:
    if path.suffix == ".csv":
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["empty"])
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--date", default="", help="folder date (default: today, UTC)")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    day = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    folder = Path(f"/Volumes/{n.catalog}/{n.schema('obs')}/exports/logs/{day}")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"generated_at": datetime.now(UTC).isoformat(), "run_id": args.run_id, "catalog": n.catalog, "files": {}}
    for name, query in EXPORTS.items():
        rows = [r.asDict(recursive=True) for r in spark.sql(query.format(obs=f"{n.catalog}.{n.schema('obs')}")).collect()]
        write(folder / name, rows)
        manifest["files"][name] = len(rows)
        print(f"{folder / name}: {len(rows)} rows")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
