"""Claude Code over MCP as each persona (T23): the same prompts, different results per user.

Claude Code runs headless (`claude -p`) from an empty folder with project settings only (no user hooks or
plugins) and examples/claude_code/mcp.json as its only MCP servers: Databricks managed MCP servers (PREVIEW) for AI Search over <catalog>.kb (both
tier indexes), the Genie space and Databricks SQL, each called with the persona's own token. Built-in tools are
off (--tools ""); only the MCP tools are allowed.

Claude Code's own model calls keep the route this machine's managed settings give it: an organisation
apiKeyHelper overrides ANTHROPIC_AUTH_TOKEN and cannot be changed per session (observed 2026-10-17), so the
model is not called as the persona. Per-user evidence for this path is the MCP calls in system.access.audit;
per-user model usage in system.ai_gateway.usage comes from the copilot, which calls Unity Gateway as the caller.

Identity: per-persona bearer tokens (OAuth machine-to-machine for the persona service principals). Claude Code's
own OAuth flow for remote MCP servers needs an OAuth app registered at the account level, which this workspace
cannot do.

Writes docs/evidence/T23/mcp_<target>.json: per persona and prompt, the MCP servers' status, the tools called,
which calls were refused and the answer. Per-user rows in system.ai_gateway.usage and system.access.audit are
collected later: system tables are not real-time.

    uv run --group dbx python tests/e2e/mcp_personas.py --target prod
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import bearer_token

REPO = Path(__file__).resolve().parents[2]
MCP = REPO / "examples" / "claude_code" / "mcp.json"
PERSONAS = {"ava": "meridian-ava", "ben": "meridian-ben", "gus": "meridian-gus"}
PROMPTS = {
    "kb_threshold": "Using the meridian-kb tools, find the refund amount above which a refund batch needs approval. "
                    "Search both indexes and cite the document id.",
    "genie_yesterday": "Using the meridian-genie tools, what was acq_7's failure rate yesterday?",
    "dev_table": "Using the meridian-sql tools with read-only SQL, how many rows does {catalog}.bronze.payments have, "
                 "and when was its most recent row ingested?",
    "finance_fee": "Using the meridian-kb tools, search the finance index: what does acq_2 charge for a bank transfer "
                   "payment?",
}
REFUSAL_MARKERS = ("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS", "does not have", "not authorized", "Forbidden")


def claude(prompt: str, env: dict, model: str) -> list[dict]:
    cmd = ["claude", "-p", prompt, "--setting-sources", "project", "--permission-mode", "default",
           "--mcp-config", str(MCP), "--strict-mcp-config", "--tools", "",
           "--allowedTools", "mcp__meridian-kb", "mcp__meridian-genie", "mcp__meridian-sql",
           "--output-format", "stream-json", "--verbose", "--max-turns", "10", "--model", model,
           "--no-session-persistence"]
    with tempfile.TemporaryDirectory() as empty:  # no project settings, CLAUDE.md or MCP servers to pick up
        out = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True, timeout=600, cwd=empty)
    events = [json.loads(line) for line in out.stdout.splitlines() if line.startswith("{")]
    if not events:
        events = [{"type": "result", "is_error": True, "result": (out.stderr or "no output")[:300]}]
    return events


def summarize(events: list[dict]) -> dict:
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    calls, outcomes = {}, []
    for e in events:
        for block in (e.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block["id"]] = {"tool": block["name"], "input": block.get("input")}
            elif block.get("type") == "tool_result":
                content = block.get("content")
                text = content if isinstance(content, str) else " ".join(
                    c.get("text", "") for c in content or [] if isinstance(c, dict))
                call = calls.get(block.get("tool_use_id"), {})
                outcomes.append({**call, "refused": bool(block.get("is_error"))
                                 or any(m in text for m in REFUSAL_MARKERS), "result": text[:240]})
    return {"mcp_servers": {s["name"]: s.get("status") for s in init.get("mcp_servers", [])},
            "model": init.get("model"), "tool_calls": outcomes, "answer": result.get("result", ""),
            "is_error": result.get("is_error"), "turns": result.get("num_turns"),
            "usage": {k: v for k, v in (result.get("usage") or {}).items() if "tokens" in k}}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    p.add_argument("--personas", default="ava,ben,gus")
    args = p.parse_args()
    t = target_names(args.target)
    admin = WorkspaceClient()
    host = admin.config.host.rstrip("/")
    title = "Meridian payments (gold)" + ("" if args.target == "prod" else f" [{args.target}]")
    space = next(s.space_id for s in admin.genie.list_spaces().spaces or [] if s.title == title)
    model = "sonnet"  # an alias the managed model route resolves

    def run(job: tuple[str, str]) -> dict:
        persona, key = job
        token = bearer_token(WorkspaceClient(profile=PERSONAS[persona]))
        env = dict(os.environ) | {"DATABRICKS_HOST": host, "MERIDIAN_MCP_TOKEN": token, "MERIDIAN_GENIE_SPACE_ID": space,
                                  "MERIDIAN_CATALOG": t.catalog, "MERIDIAN_KB": t.schemas["kb"]}
        started = datetime.now(UTC)
        s = summarize(claude(PROMPTS[key].format(catalog=t.catalog), env, model))
        return {"persona": persona, "prompt": key, "started": started.isoformat(),
                "seconds": round((datetime.now(UTC) - started).total_seconds(), 1), **s}

    jobs = [(persona, key) for persona in args.personas.split(",") for key in PROMPTS]
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(run, jobs))

    def row(persona: str, key: str) -> dict:
        return next((r for r in rows if r["persona"] == persona and r["prompt"] == key), {"tool_calls": [], "answer": ""})

    def refused(persona: str, key: str, server: str) -> list[bool]:
        return [c["refused"] for c in row(persona, key)["tool_calls"] if server in str(c.get("tool"))]

    ran = set(args.personas.split(","))
    checks = {"every MCP server connected for every persona": all(
        r["mcp_servers"] and all(v == "connected" for v in r["mcp_servers"].values()) for r in rows)}
    if "ava" in ran:
        checks["Ava: the finance index refuses her and the fee does not appear"] = (
            bool(refused("ava", "finance_fee", "idx_finance")) and all(refused("ava", "finance_fee", "idx_finance"))
            and "0.75" not in row("ava", "finance_fee")["answer"])
        checks["Ava: the bronze table refuses her"] = all(refused("ava", "dev_table", "sql"))
    if "ben" in ran:
        checks["Ben: the finance index answers him"] = "0.75" in row("ben", "finance_fee")["answer"]
    if "gus" in ran:
        checks["Gus (data engineer) reads the bronze table"] = not all(refused("gus", "dev_table", "sql"))
    result = {"task": "T23 Claude Code over MCP", "target": args.target, "at": datetime.now(UTC).isoformat(),
              "client": "Claude Code (claude -p)", "model_route": "this machine's managed settings, not the persona",
              "identity": "per-persona bearer tokens (OAuth M2M service principals)", "rows": rows,
              "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
    out = REPO / "docs" / "evidence" / "T23" / f"mcp_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    for r in rows:
        refused = sum(c["refused"] for c in r["tool_calls"])
        print(f"{r['persona']:<4} {r['prompt']:<16} calls={len(r['tool_calls'])} refused={refused} "
              f"{r['seconds']}s | {r['answer'][:110]!r}")
    print(result["status"], json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
