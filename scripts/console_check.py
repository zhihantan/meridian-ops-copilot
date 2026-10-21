"""Check the copilot app's browser console end to end, as Eli, Ben and Ava (T17 evidence).

Calls the deployed app through the Apps ingress with each persona's own token, the way the console does, and
records what each one gets:
- who they are and their knowledge tiers;
- the knowledge chatbot on a general question, a finance-tier question, and one it must not answer;
- Genie on a question, and a follow-up in the same conversation;
- approvals, and one copilot question.

Nothing is approved and no runbook runs. The approval checks use a made-up id, which the procedure refuses before
writing anything. Names never reach the evidence.

    uv run --group dbx --group agent python scripts/console_check.py
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.workspace import bearer_token

APP = "agent-bricks-meridian-copilot"
EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "T17"
PERSONAS = {"eli": None, "ben": "meridian-ben", "ava": "meridian-ava"}  # None: the presenter's own profile
GENERAL = "How long does a refund approval stay valid?"
FINANCE = "What service credit can Meridian claim when acq_7 breaches its SLA?"
OUT_OF_SCOPE = "What will the SGD to USD exchange rate be next month?"
DEGRADED = "Which acquirers are degraded right now?"
FOLLOW_UP = "And what was its failure rate on each of the last 3 days?"


class App:
    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def call(self, path: str, body: dict | None = None, headers: dict | None = None, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}{path}", data=data, method="POST" if data is not None else "GET",
                                     headers={"Authorization": f"Bearer {self.token}", **(headers or {}),
                                              **({"Content-Type": "application/json"} if data is not None else {})})
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                text = resp.read().decode()
                return resp.status, text if raw else json.loads(text)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]

    def asset(self, path: str) -> tuple[int, int, int]:
        """An asset as a browser fetches it, gzip accepted: (status, bytes sent, bytes after decompressing)."""
        req = urllib.request.Request(f"{self.url}{path}", headers={"Authorization": f"Bearer {self.token}",
                                                                    "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            plain = gzip.decompress(body) if resp.headers.get("Content-Encoding") == "gzip" else body
            return resp.status, len(body), len(plain)

    def knowledge(self, question: str) -> dict:
        started = time.time()
        status, text = self.call("/api/knowledge/ask", {"question": question}, raw=True)
        events = {}
        for block in text.split("\n\n") if status == 200 else []:
            fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
            if "event" in fields:
                events[fields["event"]] = json.loads(fields["data"])
        passages, answer = events.get("passages", {}), events.get("answer", {})
        return {"status": status, "seconds": round(time.time() - started, 1), "tiers": passages.get("tiers"),
                "passage_tiers": sorted({p["tier"] for p in passages.get("passages", [])}),
                "abstained": answer.get("abstained"), "citations": answer.get("citations"),
                "error": events.get("error", {}).get("message"), "answer": (answer.get("answer") or "")[:240]}

    def genie(self, question: str, conversation_id: str | None = None) -> dict:
        started = time.time()
        status, ids = self.call("/api/genie/ask", {"question": question, "conversation_id": conversation_id})
        if status != 200:
            return {"status": status, "error": ids}
        while True:
            status, m = self.call(f"/api/genie/{ids['conversation_id']}/{ids['message_id']}")
            if status != 200 or m["done"] or time.time() - started > 240:
                break
            time.sleep(2)
        rows = [r for q in m.get("queries", []) for r in q["rows"]] if status == 200 else []
        return {"status": m.get("status") if status == 200 else status, "seconds": round(time.time() - started, 1),
                "conversation_id": ids["conversation_id"], "queries": len(m.get("queries", [])) if status == 200 else 0,
                "rows": len(rows), "mentions_acq_7": "acq_7" in json.dumps(rows) + (m.get("text") or "") if status == 200 else False,
                "text": (m.get("text") or "")[:200] if status == 200 else m}

    def copilot(self, question: str) -> dict:
        started, session = time.time(), str(uuid.uuid4())
        status, accepted = self.call("/api/invocations", {"id": str(uuid.uuid4()), "session_id": session, "background": True,
                                                          "stream": True, "input": {"messages": [{"role": "user", "content": question}]}},
                                     headers={"X-Routing-Key": session})
        if status != 202:
            return {"status": status, "error": accepted}
        while True:
            status, state = self.call(accepted["status_url"], headers={"X-Routing-Key": session})
            if status != 200 or state["status"] in ("completed", "failed") or time.time() - started > 300:
                break
            time.sleep(2)
        out = state.get("output") or {} if status == 200 else {}
        answer = next((m["content"] for m in reversed(out.get("output", [])) if m.get("role") == "assistant" and m.get("content")), "")
        return {"status": state.get("status") if status == 200 else status, "seconds": round(time.time() - started, 1),
                "answer": answer[:240]}


def main() -> None:
    url = WorkspaceClient().apps.get(APP).url
    results: dict = {}
    for persona, profile in PERSONAS.items():
        app = App(url, bearer_token(WorkspaceClient(profile=profile) if profile else WorkspaceClient()))
        r: dict = {}
        status, me = app.call("/api/me")
        r["me"] = {"status": status, "name_present": bool(isinstance(me, dict) and me.get("name")),
                   "tiers": me.get("tiers") if isinstance(me, dict) else None, "admin": me.get("admin") if isinstance(me, dict) else None}
        r["knowledge_finance"] = app.knowledge(FINANCE)
        r["genie_degraded"] = app.genie(DEGRADED)
        if persona in ("eli", "ava"):
            r["knowledge_general"] = app.knowledge(GENERAL)
            r["copilot"] = app.copilot(GENERAL)
            status, pending = app.call("/api/approvals")
            status_recent, recent = app.call("/api/approvals/recent")
            r["approvals"] = {"status": status, "pending": len(pending.get("approvals", [])) if isinstance(pending, dict) else None,
                              "error": pending.get("error") if isinstance(pending, dict) else pending,
                              "recent": [(a["batch_id"], a["status"], a["batch_status"]) for a in recent.get("approvals", [])][:3]
                              if isinstance(recent, dict) else status_recent}
        if persona == "eli":
            status, page = app.call("/", raw=True)
            asset = re.search(r"/assets/index-[^\"]+\.js", page or "")
            bundle = app.asset(asset.group(0)) if asset else (0, 0, 0)
            r["page"] = {"status": status, "react_build": bool(asset), "bundle_status": bundle[0],
                         "bundle_bytes_sent": bundle[1], "bundle_bytes": bundle[2],
                         "classic": app.call("/classic", raw=True)[0]}
            r["knowledge_out_of_scope"] = app.knowledge(OUT_OF_SCOPE)
            r["genie_follow_up"] = app.genie(FOLLOW_UP, r["genie_degraded"].get("conversation_id"))
            status, overview = app.call("/api/overview")
            r["overview"] = {"status": status, "degraded": [a["acquirer_id"] for a in overview.get("acquirers", []) if a["status"] == "degraded"],
                             "acquirers": len(overview.get("acquirers", [])), "data_until": (overview.get("acquirers") or [{}])[0].get("data_until_sgt")}
            r["approve_without_header"] = app.call("/api/approvals/not-a-real-approval", {"reason": "console check"})[0]
            r["approve_made_up_id"] = app.call("/api/approvals/not-a-real-approval", {"reason": "console check"}, {"X-Meridian-UI": "1"})[1]
        results[persona] = r
        print(f"{persona}: done")

    eli, ben, ava = results["eli"], results["ben"], results["ava"]
    cites = lambda k, doc: any(c.startswith(doc) for c in (k.get("citations") or []))
    checks = {
        "page and bundle load (gzip), classic fallback": eli["page"]["react_build"] and eli["page"]["bundle_status"] == 200 and eli["page"]["bundle_bytes"] > 100_000 and eli["page"]["bundle_bytes_sent"] < eli["page"]["bundle_bytes"] and eli["page"]["classic"] == 200,
        "identity: Eli admin with general and finance": eli["me"]["admin"] is True and eli["me"]["tiers"] == ["general", "finance"],
        "identity: Ben general and finance, not admin": ben["me"]["admin"] is False and ben["me"]["tiers"] == ["general", "finance"],
        "identity: Ava general only, not admin": ava["me"]["admin"] is False and ava["me"]["tiers"] == ["general"],
        "knowledge: general question cites DOC-RB-021 (Eli, Ava)": cites(eli["knowledge_general"], "DOC-RB-021") and cites(ava["knowledge_general"], "DOC-RB-021"),
        "knowledge: finance clause cited for Eli and Ben": cites(eli["knowledge_finance"], "DOC-FEE-001") and cites(ben["knowledge_finance"], "DOC-FEE-001"),
        "knowledge: Ava searches no finance tier and gets no finance passage": ava["knowledge_finance"]["tiers"] == ["general"] and "finance" not in ava["knowledge_finance"]["passage_tiers"] and not cites(ava["knowledge_finance"], "DOC-FEE-001"),
        "knowledge: out-of-scope question abstains": eli["knowledge_out_of_scope"]["abstained"] is True,
        "genie: answers as each persona, naming acq_7": all(p["genie_degraded"]["status"] == "COMPLETED" and p["genie_degraded"]["mentions_acq_7"] for p in (eli, ben, ava)),
        "genie: follow-up continues the same conversation": eli["genie_follow_up"]["status"] == "COMPLETED" and eli["genie_follow_up"]["conversation_id"] == eli["genie_degraded"]["conversation_id"],
        "overview: acq_7 degraded, 7 acquirers": eli["overview"]["degraded"] == ["acq_7"] and eli["overview"]["acquirers"] == 7,
        "approvals: Eli sees the decided batch RB-832eed0860": any(b == "RB-832eed0860" and s == "approved" for b, s, _ in eli["approvals"]["recent"]) or "RB-832eed0860" in json.dumps(eli["approvals"]),
        "approvals: an approval without the console's header is rejected": eli["approve_without_header"] == 400,
        "approvals: a made-up approval gets the procedure's refusal": isinstance(eli["approve_made_up_id"], dict) and eli["approve_made_up_id"].get("approved") is False and "no pending" in eli["approve_made_up_id"].get("reason", ""),
        "copilot: answers as Eli and as Ava": eli["copilot"]["status"] == "completed" and ava["copilot"]["status"] == "completed" and bool(eli["copilot"]["answer"]) and bool(ava["copilot"]["answer"]),
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    passed = sum(checks.values())
    print(f"{passed}/{len(checks)} passed")
    out = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "app": APP,
           "result": "PASS" if passed == len(checks) else "FAIL", "checks": checks, "personas": results}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"console_check_{datetime.now(UTC):%Y-%m-%d}.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"wrote {path.relative_to(EVIDENCE.parents[2])}")


if __name__ == "__main__":
    main()
