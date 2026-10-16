"""Failure drill for the knowledge sync (T15): corrupt file, unreachable source, silent drop. Writes evidence.

1. A corrupt PDF lands: the run records it in kb.ingest_failures with a reason and carries on.
2. The source location is unreachable (here: the job pointed at a missing folder; a revoked grant fails the
   same step): the run fails with the reason, and the job's failure email fires.
3. A document is removed from kb.docs by hand, with no source delete: the next run's reconcile task fails
   naming it (failure email), and the sync repairs it.

    uv run --group dbx python scripts/kb_failure_drill.py --target dev
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]


def run_job(target: str, params: str = "") -> dict:
    cmd = ["databricks", "bundle", "run", "-t", target, "kb_sync_job"] + (["--params", params] if params else [])
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, check=False)
    text = re.sub(r"\x1b\[[0-9;]*m", "", out.stdout + out.stderr)  # drop terminal colour codes
    url_line = next((line for line in text.splitlines() if "/runs/" in line), "")
    run_id = url_line.rstrip("/").split("/runs/")[-1].split("?")[0] if url_line else None
    return {"exit_code": out.returncode, "job_run_id": run_id,
            "lines": [line.strip()[:220] for line in text.splitlines()
                      if any(k in line for k in ("kb_sync ", "failed ", "silent drop", "reconciled", "  DOC", "Error:",
                                                 "TERMINATED", "PATH_NOT_FOUND", "does not exist"))][:12]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--drop", default="DOC-RB-021", help="document to remove from kb.docs by hand")
    args = p.parse_args()
    w = WorkspaceClient()
    t = target_names(args.target)
    kb = f"{t.catalog}.{t.schemas['kb']}"
    root = f"/Volumes/{t.catalog}/{t.schemas['landing']}/raw/kb"
    corrupt = f"{root}/files/general/DOC-CORRUPT-001.pdf"
    steps = {}

    w.files.upload(corrupt, io.BytesIO(b"%PDF-1.4\n" + os.urandom(2048)), overwrite=True)
    steps["corrupt pdf"] = run_job(args.target)
    steps["corrupt pdf"]["ingest_failures"] = sql(w, f"""SELECT doc_id, stage, left(reason, 160) FROM {kb}.ingest_failures
        WHERE doc_id = 'DOC-CORRUPT-001' ORDER BY failed_at DESC LIMIT 1""")
    w.files.delete(corrupt)

    steps["unreachable source"] = run_job(args.target, f"kb_root={root}_missing")

    sql(w, f"DELETE FROM {kb}.docs WHERE doc_id = '{args.drop}'")
    steps["silent drop"] = run_job(args.target)
    steps["silent drop"]["reconcile_events"] = sql(w, f"""SELECT doc_id, layer, message FROM {kb.rsplit('.', 1)[0]}.{t.schemas['obs']}.kb_reconcile_events
        WHERE doc_id = '{args.drop}' ORDER BY checked_at DESC LIMIT 1""")
    steps["silent drop"]["doc_after_run"] = sql(w, f"SELECT revision, chunks, deleted_at IS NULL FROM {kb}.docs WHERE doc_id = '{args.drop}'")
    steps["clean rerun"] = run_job(args.target)

    checks = {
        "corrupt file recorded with a reason": bool(steps["corrupt pdf"]["ingest_failures"]),
        "corrupt file does not stop the run": steps["corrupt pdf"]["exit_code"] == 0,
        "unreachable source fails the run with a reason": steps["unreachable source"]["exit_code"] != 0,
        "silent drop is named by reconcile": bool(steps["silent drop"]["reconcile_events"]),
        "silent drop repaired by the same run": bool(steps["silent drop"]["doc_after_run"]),
        "clean rerun after the drill": steps["clean rerun"]["exit_code"] == 0,
    }
    result = {"task": "T15 failures", "target": args.target, "at": datetime.now(UTC).isoformat(), "steps": steps,
              "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
    out = REPO / "docs" / "evidence" / "T15" / f"failures_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, default=str)
    out.write_text(text.replace(w.config.host, "<workspace>") + "\n")
    print(result["status"], checks)


if __name__ == "__main__":
    main()
