"""External agent (T24): a standalone Anthropic SDK tool loop that uses Meridian's knowledge and data over MCP.

No Databricks libraries: plain HTTPS to the workspace's managed MCP servers (AI Search over <catalog>.kb, and the
Genie space), with the caller's OAuth token, and the Anthropic SDK for the model, through the workspace's
Unity Gateway with the same token (MERIDIAN_MODEL_BASE_URL and MERIDIAN_MODEL_TOKEN point it elsewhere; the
ANTHROPIC_* variables of other tools are deliberately ignored). Every tool call runs as the token's identity, so Unity Catalog decides what it can read: a support
agent's token gets PERMISSION_DENIED on the finance index.

    export DATABRICKS_HOST=https://<workspace host>
    export DATABRICKS_TOKEN=$(databricks auth token -p <profile> | jq -r .access_token)
    export MERIDIAN_GENIE_SPACE_ID=<space id>          # optional: adds the Genie tools
    python examples/external_agent/agent.py "Above what amount does a refund batch need approval?"

Requires: anthropic (pip install anthropic). Python 3.10+.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import anthropic

HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
TOKEN = os.environ["DATABRICKS_TOKEN"]
CATALOG, KB = os.environ.get("MERIDIAN_CATALOG", "meridian"), os.environ.get("MERIDIAN_KB", "kb")
MODEL = os.environ.get("MERIDIAN_MODEL", "databricks-claude-sonnet-5-5")
SERVERS = {"kb": f"/api/2.0/mcp/vector-search/{CATALOG}/{KB}"}
if os.environ.get("MERIDIAN_GENIE_SPACE_ID"):
    SERVERS["genie"] = f"/api/2.0/mcp/genie/{os.environ['MERIDIAN_GENIE_SPACE_ID']}"
SYSTEM = ("You answer questions about Meridian Commerce's payment operations using only the tools. Cite every fact "
          "with the document id and page of the passage it came from, like [DOC-RB-021 p.1], or the Genie "
          "conversation for data. If a tool is refused or returns nothing relevant, say so; do not guess.")


def rpc(server: str, method: str, params: dict | None = None) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(HOST + SERVERS[server], data=body, method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"error": {"message": f"HTTP {exc.code}"}}


def tools() -> tuple[list[dict], dict[str, str]]:
    """The MCP servers' tools as Anthropic tool definitions, and which server serves each."""
    defs, owner = [], {}
    for server in SERVERS:
        for t in rpc(server, "tools/list").get("result", {}).get("tools", []):
            defs.append({"name": t["name"], "description": t.get("description", "")[:1000],
                         "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}}})
            owner[t["name"]] = server
    return defs, owner


def call(server: str, name: str, args: dict) -> str:
    reply = rpc(server, "tools/call", {"name": name, "arguments": args})
    if "error" in reply:
        return json.dumps({"error": reply["error"].get("message", "refused")})[:4000]
    texts = [c.get("text", "") for c in reply.get("result", {}).get("content", [])]
    return "\n".join(texts)[:12000]


def main(question: str) -> str:
    client = anthropic.Anthropic(base_url=os.environ.get("MERIDIAN_MODEL_BASE_URL", f"{HOST}/ai-gateway/anthropic"),
                                 api_key="",  # the gateway takes a bearer token only
                                 auth_token=os.environ.get("MERIDIAN_MODEL_TOKEN", TOKEN))
    defs, owner = tools()
    messages = [{"role": "user", "content": question}]
    for _ in range(8):
        resp = client.messages.create(model=MODEL, max_tokens=1000, system=SYSTEM, tools=defs, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": call(owner[c.name], c.name, c.input)}
            for c in calls]})
    return "Stopped after too many tool calls."


if __name__ == "__main__":
    print(main(" ".join(sys.argv[1:]) or "Above what amount does a refund batch need approval?"))
