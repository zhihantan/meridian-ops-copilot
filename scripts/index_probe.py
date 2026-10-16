"""Index readiness and per-persona access (T13): hybrid query on each tier index as Eli, Ben and Ava. Read-only.

Waits until both indexes are online, then each persona (its own CLI profile) runs the same hybrid query
against each index. Expected: Ava (support) reads the general index and is denied the finance index;
Ben (finance) and Eli (admin) read both. Writes docs/evidence/T13/index_probe_<target>.json.

    uv run --group dbx python scripts/index_probe.py --target dev [--query "acq_7 service credit"]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names

REPO = Path(__file__).resolve().parents[1]
PERSONAS = {"eli (admin)": None, "ben (finance)": "meridian-ben", "ava (support)": "meridian-ava"}


def wait_ready(w: WorkspaceClient, index: str, timeout_s: int = 1200) -> dict:
    deadline = time.time() + timeout_s
    while True:
        status = w.vector_search_indexes.get_index(index).status
        message = re.sub(r"https?://\S+", "<url>", (status.message if status else None) or "")  # evidence is public
        if status and status.ready:
            return {"ready": True, "indexed_rows": status.indexed_row_count, "message": message}
        if time.time() > deadline:
            return {"ready": False, "message": message}
        time.sleep(15)


def query(profile: str | None, index: str, text: str) -> dict:
    w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    try:
        res = w.vector_search_indexes.query_index(index_name=index, columns=["doc_id", "page", "text"],
                                                  query_text=text, num_results=3, query_type="HYBRID")
        rows = (res.result.data_array or []) if res.result else []
        return {"result": "allowed", "top_docs": [r[0] for r in rows]}
    except Exception as exc:  # noqa: BLE001  a denial is the expected outcome for some personas
        message = str(exc).splitlines()[0].split(" Config:")[0]  # the SDK appends the host; evidence is public
        return {"result": "denied", "error": type(exc).__name__, "message": message[:140]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--query", default="acq_7 service credit when the failure rate is too high")
    args = p.parse_args()
    t = target_names(args.target)
    w = WorkspaceClient()
    indexes = {tier: f"{t.catalog}.{t.schemas['kb']}.idx_{tier}" for tier in ("general", "finance")}
    result: dict = {"task": "T13 indexes", "target": args.target, "at": datetime.now(UTC).isoformat(),
                    "query": args.query, "indexes": {}, "access": {}}
    for tier, index in indexes.items():
        result["indexes"][tier] = wait_ready(w, index)
        print(tier, result["indexes"][tier])
    for persona, profile in PERSONAS.items():
        for tier, index in indexes.items():
            got = query(profile, index, args.query)
            result["access"][f"{persona} / {tier}"] = got
            print(f"{persona:<15} {tier:<8} {got['result']:<8} {got.get('top_docs', got.get('message'))}")
    checks = {
        "both indexes online": all(i["ready"] for i in result["indexes"].values()),
        "hybrid query returns results": bool(result["access"]["eli (admin) / general"].get("top_docs")),
        "ava cannot query the finance index": result["access"]["ava (support) / finance"]["result"] == "denied",
        "ben can query the finance index": result["access"]["ben (finance) / finance"]["result"] == "allowed",
        "ava can query the general index": result["access"]["ava (support) / general"]["result"] == "allowed",
    }
    result["checks"], result["status"] = checks, "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T13" / f"index_probe_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(result["status"], checks)


if __name__ == "__main__":
    main()
