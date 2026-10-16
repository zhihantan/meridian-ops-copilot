"""Call the deployed copilot's invocation API as a given identity (T17, T19, T22): sync, stream, background."""

from __future__ import annotations

import json
import re
import time
import urllib.request
import uuid

KB_CITATION = re.compile(r"\[([A-Z][A-Z0-9-]+) p\.(\d+)\]")
GENIE_CITATION = re.compile(r"\[GENIE-([0-9a-f]{8})\]")


def post(url: str, token: str, body: dict, timeout: int = 300) -> str:
    req = urllib.request.Request(f"{url}/api/invocations", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "X-Routing-Key": body.get("session_id", "")})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def get(url: str, token: str, path: str) -> dict:
    req = urllib.request.Request(f"{url}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def messages(result: dict) -> list[dict]:
    out = result.get("output") or {}
    return (out.get("output") if isinstance(out, dict) else out) or []


def final_answer(result: dict) -> str:
    return next((m["content"] for m in reversed(messages(result))
                 if m.get("role") == "assistant" and m.get("content")), "")


def ask(url: str, token: str, question: str, session: str | None = None, background: bool = False,
        timeout_s: int = 900) -> dict:
    """One invocation (synchronous, or background with polling for long runs); returns the answer, its
    citations, tool calls and seconds taken."""
    body = {"id": str(uuid.uuid4()), "session_id": session or str(uuid.uuid4()),
            "input": {"messages": [{"role": "user", "content": question}]}}
    started = time.time()
    if background:
        post(url, token, {**body, "background": True})
        result = {}
        while time.time() - started < timeout_s:
            result = get(url, token, f"/api/invocations/{body['id']}")
            if result.get("status") in ("completed", "failed"):
                break
            time.sleep(5)
    else:
        result = json.loads(post(url, token, body))
    answer = final_answer(result)
    return {"answer": answer, "kb_citations": sorted({d for d, _ in KB_CITATION.findall(answer)}),
            "genie_citations": sorted(set(GENIE_CITATION.findall(answer))),
            "tools": [c["name"] for m in messages(result) for c in m.get("tool_calls") or []],
            "status": result.get("status"), "seconds": round(time.time() - started, 1)}
