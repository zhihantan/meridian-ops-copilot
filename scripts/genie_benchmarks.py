"""Run the Genie space's benchmarks (T22) with Genie's own evaluation API and record the results. Read-only.

Writes docs/evidence/T22/benchmarks_<target>.json: per benchmark question, Genie's assessment of its generated
SQL against the golden SQL from config/genie_space.yaml.

    uv run --group dbx python scripts/genie_benchmarks.py --target prod
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from meridian.common.localenv import load_local_env

load_local_env()
REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    args = p.parse_args()
    spec = yaml.safe_load((REPO / "config" / "genie_space.yaml").read_text())
    title = spec["title"] + ("" if args.target == "prod" else f" [{args.target}]")
    w = WorkspaceClient()
    space = next(s for s in (w.genie.list_spaces().spaces or []) if s.title == title)
    run = w.genie.genie_create_eval_run(space.space_id)
    run_id = run.eval_run_id
    for _ in range(120):
        run = w.genie.genie_get_eval_run(space.space_id, run_id)
        state = str(getattr(run, "eval_run_status", None) or getattr(run, "status", ""))
        if any(s in state.upper() for s in ("DONE", "COMPLETED", "SUCCEEDED", "FAILED", "CANCELLED")):
            break
        time.sleep(10)
    results = []
    page = w.genie.genie_list_eval_results(space.space_id, run_id)
    for r in getattr(page, "eval_results", None) or getattr(page, "results", None) or []:
        d = w.genie.genie_get_eval_result_details(space.space_id, run_id, r.result_id).as_dict()
        actual = d.get("actual_response") or []
        results.append({"question": r.as_dict().get("question"), "assessment": d.get("assessment"),
                        "genie_sql": actual[0].get("response") if isinstance(actual, list) and actual else None})
    good = sum(1 for r in results if r["assessment"] == "GOOD")
    evidence = {"task": "T22 Genie benchmarks", "target": args.target, "at": datetime.now(UTC).isoformat(),
                "space": title, "eval_run_id": run_id, "run_state": state, "good": f"{good}/{len(results)}",
                "results": results}
    out = REPO / "docs" / "evidence" / "T22" / f"benchmarks_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    print(state, f"{good}/{len(results)} GOOD")
    for r in results:
        print(f"  {r['assessment']:<6} {r['question']}")


if __name__ == "__main__":
    main()
