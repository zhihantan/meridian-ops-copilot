"""Score a deployed pipeline against planted.json from a laptop (T03 to T05 evidence).

The checks are in meridian.common.score, shared with the in-workspace integration job (T09). Exits non-zero on
any FAIL.

    uv run --group dbx python scripts/score_pipeline.py --target dev --planted data/out/planted.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.score import ALL_BATCHES, score
from meridian.common.workspace import sql

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="dev")
    parser.add_argument("--planted", type=Path, default=Path("data/out/planted.json"))
    parser.add_argument("--landed", default=ALL_BATCHES,
                        help="payments batches that were landed, for the expected bronze count")
    args = parser.parse_args()

    planted = json.loads(args.planted.read_text())
    w = WorkspaceClient()
    results = score(planted, target_names(args.target).table, lambda statement: sql(w, statement), args.landed)

    failed = [r for r in results if r["status"] == "FAIL"]
    out = EVIDENCE / "T03" / f"score_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"target": args.target, "scored_at": datetime.now(UTC).isoformat(),
                               "anchor": planted["anchor"], "results": results,
                               "status": "FAIL" if failed else "PASS"}, indent=2))
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS -> {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
