"""Call the deployed copilot as each persona, in sync, stream and background modes (T17).

Grants the persona groups CAN USE on the app (idempotent), then each persona calls /api/invocations with its
own OAuth token: Ava (support) and Ben (finance) ask a general and a finance question. Expected: both get a
cited general answer; Ben gets a cited finance answer; Ava gets "I don't have that in the knowledge base".
Writes docs/evidence/T17/copilot_probe.json.

    uv run --group dbx python scripts/copilot_probe.py --app agent-bricks-meridian-copilot
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppAccessControlRequest, AppPermissionLevel

from meridian.common.workspace import bearer_token

REPO = Path(__file__).resolve().parents[1]
PERSONAS = {"ava (support)": "meridian-ava", "ben (finance)": "meridian-ben"}
QUESTIONS = {"general": "Who approves refund batches above SGD 500?",
             "finance": "What can Meridian claim from acq_7 when it breaches its SLA?"}
CITATION = re.compile(r"\[([A-Z][A-Z0-9-]+) p\.(\d+)\]")


def call(url: str, token: str, body: dict, stream: bool = False) -> tuple[int, str]:
    req = urllib.request.Request(f"{url}/api/invocations", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "X-Routing-Key": body["session_id"]})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.status, resp.read().decode()


def get(url: str, token: str, path: str) -> dict:
    req = urllib.request.Request(f"{url}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def final_answer(result: dict) -> str:
    out = result.get("output") or {}
    msgs = out.get("output") if isinstance(out, dict) else out
    return next((m["content"] for m in reversed(msgs or []) if m.get("role") == "assistant" and m.get("content")), "")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--app", default="agent-bricks-meridian-copilot")
    args = p.parse_args()
    w = WorkspaceClient()
    app = w.apps.get(args.app)
    w.apps.update_permissions(args.app, access_control_list=[
        AppAccessControlRequest(group_name=g, permission_level=AppPermissionLevel.CAN_USE)
        for g in ("meridian-support", "meridian-finance", "meridian-admin")])
    results: dict = {"task": "T17 copilot", "app": args.app, "at": datetime.now(UTC).isoformat(), "calls": []}
    for persona, profile in PERSONAS.items():
        token = bearer_token(WorkspaceClient(profile=profile))
        for kind, question in QUESTIONS.items():
            session = str(uuid.uuid4())
            body = {"id": str(uuid.uuid4()), "session_id": session,
                    "input": {"messages": [{"role": "user", "content": question}]}}
            started = time.time()
            _, text = call(app.url, token, body)
            answer = final_answer(json.loads(text))
            results["calls"].append({"persona": persona, "question": kind, "mode": "sync",
                                     "seconds": round(time.time() - started, 1), "answer": answer[:400],
                                     "citations": sorted({d for d, _ in CITATION.findall(answer)})})
            print(f"{persona:<14} {kind:<8} {answer[:110]!r}")
    # Stream and background as Ben, on the finance question.
    token = bearer_token(WorkspaceClient(profile="meridian-ben"))
    session = str(uuid.uuid4())
    _, sse = call(app.url, token, {"id": str(uuid.uuid4()), "session_id": session, "stream": True,
                                   "input": {"messages": [{"role": "user", "content": QUESTIONS["finance"]}]}})
    events = [line.split(":", 1)[1].strip() for line in sse.splitlines() if line.startswith("event:")]
    results["stream"] = {"events": events}
    inv = str(uuid.uuid4())
    _, queued = call(app.url, token, {"id": inv, "session_id": session, "background": True,
                                      "input": {"messages": [{"role": "user", "content": QUESTIONS["general"]}]}})
    status = json.loads(queued).get("status")
    for _ in range(60):
        polled = get(app.url, token, f"/api/invocations/{inv}")
        if polled.get("status") in ("completed", "failed"):
            break
        time.sleep(3)
    results["background"] = {"initial": status, "final": polled.get("status"), "answer": final_answer(polled)[:300]}
    print("stream events:", events, "| background:", status, "->", polled.get("status"))

    by = {(c["persona"], c["question"]): c for c in results["calls"]}
    checks = {
        "ben gets a cited finance answer": "DOC-FEE-001" in by[("ben (finance)", "finance")]["citations"],
        "ava is not given finance content": "DOC-FEE-001" not in by[("ava (support)", "finance")]["citations"]
        and "don't have that" in by[("ava (support)", "finance")]["answer"],
        "both get a cited general answer": all(by[(p, "general")]["citations"] for p in PERSONAS),
        "stream mode emits events": "message" in events,
        "background mode completes": results["background"]["final"] == "completed",
    }
    results["checks"], results["status"] = checks, "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T17" / "copilot_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2).replace(app.url, "<app-url>") + "\n")
    print(results["status"], checks)


if __name__ == "__main__":
    main()
