"""Recent runs of every job in a bundle target, with what triggered each (T06 evidence). Read-only.

The Jobs API is immediate, unlike system.lakeflow tables. The trigger type comes from the run
(FILE_ARRIVAL, TABLE, PERIODIC for cron, RUN_JOB_TASK, ONE_TIME for manual). Note that a Delta
table's DESCRIBE HISTORY reports "manual" for table-triggered runs, so use the run, not the history.

    uv run --group dbx python scripts/job_runs.py --target prod [--limit 5] [--out docs/evidence/T06/triggers_prod.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from databricks.sdk import WorkspaceClient

from meridian.common.localenv import load_local_env

load_local_env()

SGT = ZoneInfo("Asia/Singapore")


def sgt(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, SGT).strftime("%Y-%m-%d %H:%M:%S SGT") if ms else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--out")
    args = p.parse_args()
    summary = json.loads(subprocess.run(["databricks", "bundle", "summary", "-t", args.target, "-o", "json"],
                                        capture_output=True, text=True, check=True).stdout)
    w = WorkspaceClient()
    jobs = {}
    for key, job in sorted(summary["resources"].get("jobs", {}).items()):
        if not job.get("id"):
            continue
        runs = []
        for r in w.jobs.list_runs(job_id=int(job["id"]), limit=args.limit):
            runs.append({"run_id": r.run_id, "trigger": r.trigger.value if r.trigger else None,
                         "state": (r.state.result_state or r.state.life_cycle_state).value,
                         "started": sgt(r.start_time),
                         "seconds": round((r.end_time - r.start_time) / 1000) if r.end_time else None})
        jobs[key] = {"name": job["name"], "job_id": job["id"], "runs": runs}
        print(f"{job['name']}")
        for run in runs:
            print(f"  {run['run_id']:>17}  {run['trigger'] or '':<13} {run['state']:<22} {run['started']}")
    fired = sorted({(r["trigger"], k) for k, j in jobs.items() for r in j["runs"]
                    if r["state"] in ("SUCCESS", "SUCCESS_WITH_FAILURES")})
    result = {"task": "T06 triggers", "target": args.target, "collected_at": datetime.now(UTC).isoformat(),
              "successful_trigger_types": sorted({t for t, _ in fired if t}), "jobs": jobs}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
