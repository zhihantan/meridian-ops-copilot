"""POC scorecard (T29): every requirement with the tasks that answer it and their evidence status, as a table.

Reads, locally, the requirement rows of the build spec's coverage matrix (a private file passed in --spec; nothing
from it is in this repo) and docs/evidence/INDEX.md, then rewrites <catalog>.obs.evidence in the workspace with one
row per requirement:
- its ID and text;
- the tasks that answer it and the planned coverage;
- a status from those tasks' evidence: the weakest of them, or "answer sheet" when no task builds it;
- the headline and the evidence path.
The ops dashboard shows it on its scorecard page.

    uv run --group dbx python scripts/publish_scorecard.py --target prod --spec ../<build spec>.md
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]
RANK = {"PASS": 0, "PARTIAL": 1, "OPEN": 2, "SKIPPED": 3}
TASK = re.compile(r"\b(T\d{2}[a-z]?|SM\d)\b")


def rows(markdown: str, first_cell: re.Pattern) -> list[list[str]]:
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in markdown.splitlines()
            if line.startswith("|") and first_cell.match(line.strip("| ").split("|")[0].strip())]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    p.add_argument("--spec", required=True, help="the build spec (private, not in the repo)")
    args = p.parse_args()
    spec = Path(args.spec).read_text()
    matrix = spec[spec.index("## 4."):spec.index("## 5.")]
    requirements = rows(matrix, re.compile(r"^[A-Z]{2,4}[-+]\d"))  # DLC+n: scope additions
    index = {r[0]: r for r in rows((REPO / "docs" / "evidence" / "INDEX.md").read_text(), re.compile(r"^(T\d|SM)"))}
    status_of = {}
    for task_cell, row in index.items():
        for task in TASK.findall(task_cell):
            status_of[task] = (row[1], row[3], row[2].strip("`"))

    out = []
    for r in requirements:
        req_id, requirement, approach, tasks_cell, coverage = (r + [""] * 5)[:5]
        tasks = TASK.findall(tasks_cell)
        known = [status_of[t] for t in tasks if t in status_of]
        if not known:
            status, headline, evidence = "answer sheet", approach, ""
        else:
            worst = max(known, key=lambda k: RANK.get(k[0], 9))
            status = worst[0]
            headline = "; ".join(k[1] for k in known)[:600]
            evidence = ", ".join(f"docs/evidence/{t}/" for t in tasks if t in status_of)
        out.append((req_id, requirement, ", ".join(tasks), coverage, status, headline, evidence))

    t = target_names(args.target)
    table = f"{t.catalog}.{t.schemas['obs']}.evidence"
    w = WorkspaceClient()
    sql(w, f"""CREATE TABLE IF NOT EXISTS {table} (req_id STRING, requirement STRING, tasks STRING, coverage STRING,
               status STRING, headline STRING, evidence STRING, updated_at TIMESTAMP)
               COMMENT 'BUILD: POC scorecard: each requirement, the tasks that answer it and their evidence status'""")
    values = ", ".join(f"(:r{i}, :q{i}, :t{i}, :c{i}, :s{i}, :h{i}, :e{i}, current_timestamp())" for i in range(len(out)))
    params = {f"{k}{i}": v for i, row in enumerate(out) for k, v in zip("rqtcshe", row, strict=True)}
    sql(w, f"INSERT OVERWRITE {table} VALUES {values}", parameters=params)
    counts = {}
    for row in out:
        counts[row[4]] = counts.get(row[4], 0) + 1
    print(f"{table}: {len(out)} requirements; {counts}")


if __name__ == "__main__":
    main()
