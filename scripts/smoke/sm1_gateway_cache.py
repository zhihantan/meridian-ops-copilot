"""SM1: Claude through Unity Gateway's native Anthropic path, with prompt caching.

Two calls share a long system prompt marked with cache_control. PASS when the second call reads
from the cache. The same calls later appear in system.ai_gateway.usage (not real-time; check later).

    uv run --group agent --group dbx python scripts/smoke/sm1_gateway_cache.py
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from databricks.sdk import WorkspaceClient

MODEL = "databricks-claude-sonnet-5-5"
EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "SM1"


def long_system_prompt() -> str:
    # About 6k tokens of stable text: well above the minimum cacheable prefix for current models.
    clauses = [
        f"Clause {i}: when acquirer acq_{i % 7 + 1} reports elevated failures, confirm the failure rate from data, "
        "retrieve the approved runbook, compute impact from governed tables only, and never act without the "
        "required approval recorded by a different person than the requester."
        for i in range(160)
    ]
    return "You are the Meridian Ops Copilot smoke test.\n" + "\n".join(clauses)


def main() -> None:
    w = WorkspaceClient()
    token = w.config.authenticate()["Authorization"].split(" ", 1)[1]
    client = anthropic.Anthropic(base_url=f"{w.config.host}/ai-gateway/anthropic", auth_token=token)
    system = [{"type": "text", "text": long_system_prompt(), "cache_control": {"type": "ephemeral"}}]

    calls = []
    for attempt in (1, 2):
        start = time.time()
        msg = client.messages.create(
            model=MODEL, max_tokens=16, system=system,
            messages=[{"role": "user", "content": f"Smoke test call {attempt}: reply OK."}],
        )
        u = msg.usage
        calls.append({
            "attempt": attempt, "seconds": round(time.time() - start, 2), "input_tokens": u.input_tokens,
            "cache_creation_input_tokens": u.cache_creation_input_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens, "output_tokens": u.output_tokens,
        })
        print(calls[-1])

    status = "PASS" if calls[1]["cache_read_input_tokens"] > 0 else "FAIL"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "result.json").write_text(json.dumps({
        "test": "SM1 gateway native Anthropic path with prompt caching", "model": MODEL,
        "path": "/ai-gateway/anthropic/v1/messages", "ran_at": datetime.now(UTC).isoformat(),
        "calls": calls, "status": status,
        "follow_up": "find both calls in system.ai_gateway.usage once ingested (pre-stage for T27)",
    }, indent=2))
    print(status)


if __name__ == "__main__":
    main()
