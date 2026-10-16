"""Mixed questions (T22): answers that need both Genie and the knowledge base, from the deployed copilot.

Asks each question in config/mixed_questions.yaml as Ben (finance) and counts answers that carry both a Genie
citation and a knowledge-base citation. Writes docs/evidence/T22/mixed_<app>.json.

    uv run --group dbx python scripts/eval_mixed.py --app agent-bricks-meridian-copilot
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from meridian.agent.client import ask
from meridian.common.workspace import bearer_token

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--app", default="agent-bricks-meridian-copilot")
    p.add_argument("--persona", default="meridian-ben")
    args = p.parse_args()
    url = WorkspaceClient().apps.get(args.app).url
    token = bearer_token(WorkspaceClient(profile=args.persona))
    questions = yaml.safe_load((REPO / "config" / "mixed_questions.yaml").read_text())["questions"]
    with ThreadPoolExecutor(max_workers=2) as pool:  # long runs: background invocations, polled
        answers = list(pool.map(lambda q: ask(url, token, q["question"], background=True), questions))
    rows = []
    for q, a in zip(questions, answers, strict=True):
        both = bool(a["genie_citations"]) and bool(a["kb_citations"])
        expected_kb = bool(set(q["kb"]) & set(a["kb_citations"]))
        rows.append({"id": q["id"], "both_citation_types": both, "cites_an_expected_doc": expected_kb, **a})
        print(f"{q['id']} both={both!s:<5} kb={a['kb_citations']} genie={a['genie_citations']} {a['seconds']}s")
    both = sum(r["both_citation_types"] for r in rows)
    result = {"task": "T22 mixed questions", "app": args.app, "persona": args.persona,
              "at": datetime.now(UTC).isoformat(), "both_citation_types": f"{both}/{len(rows)}",
              "status": "PASS" if both >= 6 else "FAIL", "rows": rows}
    out = REPO / "docs" / "evidence" / "T22" / "mixed_prod.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], result["both_citation_types"])


if __name__ == "__main__":
    main()
