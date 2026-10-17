"""Collect a meridian-integration-test run as evidence (T09): its task timings and the scores from the run's folder.

Writes docs/evidence/T09/integration_<name>.json.

    uv run --group dbx python scripts/integration_evidence.py --name pass --ref main@<sha> [--run-id N]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names

REPO = Path(__file__).resolve().parents[1]
JOB = "meridian-integration-test"


def minutes(start: int | None, end: int | None) -> float | None:
    return round((end - start) / 60000, 1) if start and end else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True, help="evidence name, e.g. pass or weakened")
    p.add_argument("--ref", required=True, help="what was deployed to staging, e.g. main@<sha>")
    p.add_argument("--run-id", type=int, help="default: the job's latest run")
    args = p.parse_args()
    t = target_names("staging")
    w = WorkspaceClient()
    job = next(j for j in w.jobs.list(name=JOB))
    run = w.jobs.get_run(args.run_id or next(iter(w.jobs.list_runs(job_id=job.job_id, limit=1))).run_id)
    folder = f"/Volumes/{t.catalog}/{t.schemas['obs']}/exports/integration/{run.run_id}"
    try:
        score = json.loads(w.files.download(f"{folder}/score.json").contents.read())
    except Exception as exc:  # noqa: BLE001  no scores if the run failed before the score step
        score = {"status": "not scored", "error": str(exc).splitlines()[0][:160]}
    results = score.get("results", [])
    out = {
        "job": JOB, "run_id": run.run_id, "deployed": args.ref,
        "result": str(run.state.result_state).split(".")[-1], "minutes": minutes(run.start_time, run.end_time),
        "tasks": [{"task": k.task_key, "result": str(k.state.result_state).split(".")[-1],
                   "minutes": minutes(k.start_time, k.end_time),
                   **({"message": k.state.state_message[:300]} if k.state.state_message else {})}
                  for k in sorted(run.tasks or [], key=lambda k: k.start_time or 0)],
        "score": {"status": score.get("status"), "passed": sum(r["status"] == "PASS" for r in results),
                  "checks": len(results), "failed": [r["check"] for r in results if r["status"] == "FAIL"]},
        "anchor": score.get("anchor"), "results": results,
    }
    path = REPO / "docs" / "evidence" / "T09" / f"integration_{args.name}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"{path.relative_to(REPO)}: run {run.run_id} {out['result']} in {out['minutes']} min, "
          f"{out['score']['passed']}/{out['score']['checks']} checks; failed {out['score']['failed']}")


if __name__ == "__main__":
    main()
