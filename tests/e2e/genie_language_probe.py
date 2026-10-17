"""Questions in another language to the Genie space (T22): the same questions in English and Mandarin.

Asks each pair in the target's Genie space as the presenter and records Genie's SQL, result rows and text reply.
Checks that both languages return the same rows, and records which language each reply is in. The space's
instructions and metadata are in English only.

Writes docs/evidence/T22/genie_language_<target>.json.

    uv run --group dbx python tests/e2e/genie_language_probe.py --target dev
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

REPO = Path(__file__).resolve().parents[2]
PAIRS = [
    ("Which acquirers are degraded right now?", "现在哪些收单机构处于降级状态？"),
    ("What is acq_7's failure rate in the last 24 hours?", "acq_7 过去24小时的失败率是多少？"),
]
CJK = re.compile(r"[一-鿿]")


def ask(w: WorkspaceClient, space_id: str, question: str) -> dict:
    message = w.genie.start_conversation_and_wait(space_id, question)
    out = {"question": question, "status": str(message.status), "sql": None, "rows": None, "text": None}
    for a in message.attachments or []:
        if a.query:
            out["sql"] = " ".join((a.query.query or "").split())
            out["description"] = a.query.description
            result = w.genie.get_message_attachment_query_result(space_id, message.conversation_id, message.id,
                                                                 a.attachment_id).statement_response
            out["rows"] = (result.result.data_array if result and result.result else None) or []
        if a.text:
            out["text"] = a.text.content
    reply = " ".join(filter(None, [out.get("description"), out["text"]]))
    out["reply_language"] = "Mandarin" if CJK.search(reply) else "English" if reply else "none"
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    args = p.parse_args()
    spec = yaml.safe_load((REPO / "config" / "genie_space.yaml").read_text())
    title = spec["title"] + ("" if args.target == "prod" else f" [{args.target}]")
    w = WorkspaceClient()
    space = next(s for s in (w.genie.list_spaces().spaces or []) if s.title == title)
    results = []
    for english, mandarin in PAIRS:
        en, zh = ask(w, space.space_id, english), ask(w, space.space_id, mandarin)
        results.append({"english": en, "mandarin": zh, "same_rows": en["rows"] == zh["rows"]})
        print(f"{english}\n  en: {en['sql']} -> {en['rows']} ({en['reply_language']})\n"
              f"  zh: {zh['sql']} -> {zh['rows']} ({zh['reply_language']})")
    checks = {"same_rows_in_both_languages": all(r["same_rows"] for r in results)}
    replies = sorted({r["mandarin"]["reply_language"] for r in results})
    status = "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T22" / f"genie_language_{args.target}.json"
    out.write_text(json.dumps({"target": args.target, "ran_at": datetime.now(UTC).isoformat(), "space": title,
                               "results": results, "checks": checks, "mandarin_reply_languages": replies,
                               "status": status}, indent=2, ensure_ascii=False, default=str) + "\n")
    print(checks, "Mandarin replies in:", replies, status)


if __name__ == "__main__":
    main()
