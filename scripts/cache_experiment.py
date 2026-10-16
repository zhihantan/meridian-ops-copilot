"""Prompt caching on and off (T27): identical-prefix calls through Unity Gateway, with the tokens read back.

Sends --calls requests whose prefix is the copilot's own system prompt and tool definitions (identical every time,
above the model's minimum cacheable length) and whose last message varies, first with cache_control on the system
prompt and the last tool, then with no cache_control. Each response's usage gives input, cache-write and
cache-read tokens at once; system.ai_gateway.usage has the same calls later (it is not real-time), which
scripts/cost_report.py prices. Calls run as the caller of this script. Writes docs/evidence/T27/cache_calls.json.

    uv run --group dbx --group agent python scripts/cache_experiment.py --calls 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "copilot"))
from copilot.loop import SYSTEM  # the copilot's own prefix
from copilot.tools import DEFINITIONS

from meridian.agent.answer import CONFIG, gateway_client


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--calls", type=int, default=30, help="calls per mode")
    args = p.parse_args()
    w = WorkspaceClient()
    client = gateway_client(w)
    started = datetime.now(UTC)
    calls = []
    for mode in ("cache on", "cache off"):
        cached = mode == "cache on"
        system = [{"type": "text", "text": SYSTEM} | ({"cache_control": {"type": "ephemeral"}} if cached else {})]
        tools = [*DEFINITIONS[:-1], DEFINITIONS[-1] | ({"cache_control": {"type": "ephemeral"}} if cached else {})]
        for i in range(args.calls):
            t0 = time.time()
            resp = client.messages.create(model=CONFIG["answer_model"], max_tokens=10, system=system, tools=tools,
                                          messages=[{"role": "user", "content": f"Reply with just the number {i}. "
                                                                                "Do not use any tool."}])
            u = resp.usage
            calls.append({"mode": mode, "i": i, "seconds": round(time.time() - t0, 2), "input": u.input_tokens,
                          "cache_write": u.cache_creation_input_tokens or 0, "cache_read": u.cache_read_input_tokens or 0,
                          "output": u.output_tokens})
        time.sleep(2)

    def total(mode: str, key: str) -> int:
        return sum(c[key] for c in calls if c["mode"] == mode)

    summary = {mode: {"calls": sum(1 for c in calls if c["mode"] == mode)}
               | {k: total(mode, k) for k in ("input", "cache_write", "cache_read", "output")}
               | {"median_seconds": sorted(c["seconds"] for c in calls if c["mode"] == mode)[args.calls // 2]}
               for mode in ("cache on", "cache off")}
    result = {"task": "T27 prompt caching", "model": CONFIG["answer_model"], "requester": "eli (the presenter)",
              "window_utc": [started.strftime("%Y-%m-%d %H:%M:%S"), datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")],
              "prefix": "copilot system prompt and tool definitions", "summary": summary, "calls": calls}
    out = REPO / "docs" / "evidence" / "T27" / "cache_calls.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(summary, indent=1), result["window_utc"])


if __name__ == "__main__":
    main()
