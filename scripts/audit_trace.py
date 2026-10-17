"""Trace answers to their sources (T21): version, last editor, time and reason for every cited document.

Asks a few questions as a persona, through the retriever and answer step the copilot uses: one answered from a
file, one from Slack, and one from an approved correction (T20) when there is one. Each cited document is looked up
in obs.v_kb_changes. Then today's audit export must exist on the exports volume (run meridian-daily first).
Writes docs/evidence/T21/trace_<target>.json.

    uv run --group dbx --group agent python scripts/audit_trace.py --target dev
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.agent.answer import CONFIG, answer, gateway_client
from meridian.common.bundle import target_names
from meridian.common.personas import principal_names, scrub
from meridian.common.workspace import sql
from meridian.kb.retrieve import Retriever

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = ["Above what amount does a refund batch need approval?",
             "Which PagerDuty schedule is the PayOps on-call?"]
FIELDS = ("doc_id", "source", "tier", "source_version", "revision", "synced_at", "last_editor", "edited_at", "change",
          "correction_submitted_by", "last_audit_actor", "last_audit_action", "last_audit_reason", "last_audit_at")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--persona", default="meridian-ava")
    args = p.parse_args()
    t = target_names(args.target)
    kb, obs = f"{t.catalog}.{t.schemas['kb']}", f"{t.catalog}.{t.schemas['obs']}"
    admin = WorkspaceClient()
    retriever, model = Retriever(WorkspaceClient(profile=args.persona), kb), gateway_client(admin)
    served = sql(admin, f"""SELECT c.title FROM {kb}.corrections c JOIN {kb}.docs d ON d.doc_id = c.correction_id
                            WHERE c.status = 'approved' AND c.tier = 'general' AND d.deleted_at IS NULL LIMIT 1""")
    questions = QUESTIONS + ([f"{served[0][0]}: what should I do?"] if served else [])

    traces = []
    for question in questions:
        a = answer(model, question, retriever.search(question, CONFIG["retrieval_variant"], CONFIG["top_k"]))
        cited = sorted({d for d, _ in a["citations"]})
        rows = sql(admin, f"SELECT {', '.join(FIELDS)} FROM {obs}.v_kb_changes WHERE doc_id IN "
                          f"({', '.join(':d' + str(i) for i in range(len(cited)))})",
                   parameters={f"d{i}": d for i, d in enumerate(cited)}) if cited else []
        traces.append({"question": question, "answer": a["answer"], "cited": cited,
                       "provenance": [dict(zip(FIELDS, r)) for r in rows]})
        print(question, "->", cited)
        for r in rows:
            print("   ", dict(zip(FIELDS, r)))

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    folder = f"/Volumes/{t.catalog}/{t.schemas['obs']}/exports/audit/{day}"
    try:
        files = sorted(e.name for e in admin.files.list_directory_contents(folder))
    except Exception as exc:  # noqa: BLE001  a missing folder is the failing outcome
        files = [f"missing: {type(exc).__name__}"]

    def traced(row: dict) -> bool:  # version, who, when and why, from the source or else from the last sync
        return all((row.get("source_version") or row.get("revision"), row.get("last_editor") or row.get("last_audit_actor"),
                    row.get("edited_at") or row.get("synced_at"), row.get("change")))

    checks = {"every answer cites at least one document": all(tr["cited"] for tr in traces),
              "every cited document has version, editor or sync, time and reason": all(
                  len(tr["provenance"]) == len(tr["cited"]) and all(traced(r) for r in tr["provenance"])
                  for tr in traces),
              "a correction's approver and reason are traceable": any(
                  r["source"] == "correction" and r["last_editor"] for tr in traces for r in tr["provenance"]),
              "today's audit export exists": "manifest.json" in files}
    result = {"task": "T21 audit", "target": args.target, "at": datetime.now(UTC).isoformat(), "traces": traces,
              "export_folder": folder.replace(t.catalog, "<catalog>", 1), "export_files": files, "checks": checks,
              "status": "PASS" if all(checks.values()) else "FAIL"}
    out = REPO / "docs" / "evidence" / "T21" / f"trace_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scrub(result, principal_names(admin)), indent=2) + "\n")
    print(files)
    print(result["status"], json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
