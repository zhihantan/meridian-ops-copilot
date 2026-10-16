"""Incremental sync drill (T12): unchanged rerun, edit, delete, re-add and full refresh, with counts.

Each step changes the landing volume through the Files API, runs the deployed kb_sync job, and reads
that run's row from kb.sync_runs. Writes docs/evidence/T12/drill_<target>.json.

    uv run --group dbx python scripts/kb_drill.py --target dev [--doc DOC-RB-009]
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]
COUNTS = ("source_docs", "new", "changed", "unchanged", "deleted", "failed", "chunks_written", "chunks_deleted")


def run_sync(target: str, full_refresh: bool = False) -> str:
    cmd = ["databricks", "bundle", "run", "-t", target, "kb_sync_job", "--params",
           f"full_refresh={'true' if full_refresh else 'false'}"]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, check=True).stdout
    return next(line.split()[1].rstrip(":") for line in out.splitlines() if line.startswith("kb_sync "))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--doc", default="DOC-RB-009", help="general-tier Markdown document to edit and delete")
    args = p.parse_args()
    w = WorkspaceClient()
    t = target_names(args.target)
    kb = f"{t.catalog}.{t.schemas['kb']}"
    path = f"/Volumes/{t.catalog}/{t.schemas['landing']}/raw/kb/files/general/{args.doc}.md"
    original = w.files.download(path).contents.read()

    def counts(run_id: str) -> dict:
        row = sql(w, f"SELECT {', '.join(COUNTS)} FROM {kb}.sync_runs WHERE run_id = '{run_id}'")[0]
        return dict(zip(COUNTS, (int(v) for v in row)))

    def revision() -> list:
        return sql(w, f"SELECT revision, chunks, deleted_at IS NOT NULL FROM {kb}.docs WHERE doc_id = '{args.doc}'")

    steps = []

    def step(name: str, full_refresh: bool = False) -> None:
        run_id = run_sync(args.target, full_refresh)
        steps.append({"step": name, "run_id": run_id, **counts(run_id), "doc_revision_chunks_deleted": revision()})
        print(f"{name:<22} {steps[-1]}")

    step("rerun, nothing changed")
    w.files.upload(path, io.BytesIO(original + b"\nRevision note: the hold code is shown on the payout report.\n"),
                   overwrite=True)
    step(f"edit {args.doc}")
    w.files.delete(path)
    step(f"delete {args.doc}")
    w.files.upload(path, io.BytesIO(original), overwrite=True)
    step(f"re-add {args.doc}")
    step("full refresh", full_refresh=True)

    by = {s["step"]: s for s in steps}
    checks = {
        "a rerun with no changes rewrites nothing": by["rerun, nothing changed"]["chunks_written"] == 0,
        "an edit reprocesses only that document": by[f"edit {args.doc}"]["changed"] == 1
        and by[f"edit {args.doc}"]["new"] == 0,
        "a source delete removes its chunks": by[f"delete {args.doc}"]["deleted"] == 1
        and by[f"delete {args.doc}"]["chunks_deleted"] >= 1,
        "full refresh reprocesses every document": by["full refresh"]["changed"] + by["full refresh"]["new"]
        == by["full refresh"]["source_docs"] - by["full refresh"]["failed"],
    }
    result = {"task": "T12 incremental sync", "target": args.target, "at": datetime.now(UTC).isoformat(),
              "doc": args.doc, "steps": steps, "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
    out = REPO / "docs" / "evidence" / "T12" / f"drill_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(result["status"], checks)


if __name__ == "__main__":
    main()
