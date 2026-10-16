"""Leakage matrix (T19): finance-only questions as Ava (general tier) and Ben (finance), on every path.

Questions: config/leakage_questions.yaml, six facts that exist only in DOC-FEE-001 (finance tier). Paths, each
with the persona's own credentials:
  agent  the deployed copilot's invocation API
  index  a direct query of each tier's AI Search index
  mcp    the managed MCP server for AI Search (/api/2.0/mcp/vector-search/<catalog>/<schema>), the path Claude
         Code and other MCP clients use (T23)
A leak is a forbidden fact, or DOC-FEE-001, in anything Ava receives. Ben must get DOC-FEE-001 (a cited answer on
the agent path). Then Ben is removed from meridian-finance and asked again on every path (access must drop; the
time until the finance index refuses him is recorded), and put back. Last, every span of Ava's agent traces
(<catalog>.agent.copilot_otel_spans: retrieval outputs, model inputs and outputs) is searched for the finance
document and the forbidden facts: none may have entered the model's context.

The limit, stated: row filters and column masks on a source table do not carry into an AI Search index. The
tiering here is a design we built: one index per tier, Unity Catalog SELECT per index, and the agent's choice of
indexes from the caller's own groups (meridian.kb.retrieve).

    uv run --group dbx --group agent python tests/e2e/leakage_probe.py --target prod --app agent-bricks-meridian-copilot
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.ai_search.client import AISearchClient
from databricks.sdk import WorkspaceClient

from meridian.agent.client import ask
from meridian.common.bundle import target_names
from meridian.common.workspace import bearer_token, sql
from meridian.kb.retrieve import COLUMNS

REPO = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((REPO / "config" / "leakage_questions.yaml").read_text())
DOC = SPEC["source_doc_id"]
ENDPOINT = "meridian-search"
GROUPS_API = "/api/2.0/account/scim/v2/Groups"


def short(exc: Exception | str) -> str:
    return re.sub(r"https?://\S+", "<workspace>", str(exc)).split("\n")[0][:200]


def leaks(q: dict, text: str, doc_ids: list[str]) -> list[str]:
    found = [f for f in q["forbidden_facts"] if f in text]
    return found + ([DOC] if DOC in text or DOC in doc_ids else [])


class Paths:
    """The three ways a persona can reach the knowledge base, each with their own token."""

    def __init__(self, w: WorkspaceClient, catalog: str, kb_schema: str, url: str | None):
        self.w, self.catalog, self.kb, self.url = w, catalog, kb_schema, url

    def index(self, tier: str, query: str) -> dict:
        try:
            client = AISearchClient(workspace_url=self.w.config.host, personal_access_token=bearer_token(self.w),
                                    disable_notice=True)
            res = client.get_index(ENDPOINT, f"{self.catalog}.{self.kb}.idx_{tier}").similarity_search(
                columns=COLUMNS, query_text=query, num_results=5, query_type="HYBRID", disable_notice=True)
        except Exception as exc:  # noqa: BLE001  a refusal is the expected outcome for a non-entitled caller
            return {"denied": True, "error": short(exc), "doc_ids": [], "text": ""}
        names = [c["name"] for c in res.get("manifest", {}).get("columns", [])]
        rows = [dict(zip(names, r)) for r in res.get("result", {}).get("data_array") or []]
        return {"denied": False, "doc_ids": [r["doc_id"] for r in rows], "text": " ".join(r["text"] for r in rows)}

    def mcp(self, tier: str, query: str) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": f"{self.catalog}__{self.kb}__idx_{tier}", "arguments": {"query": query}}}
        req = urllib.request.Request(f"{self.w.config.host}/api/2.0/mcp/vector-search/{self.catalog}/{self.kb}",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {bearer_token(self.w)}",
                                              "Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                reply = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return {"denied": True, "error": f"HTTP {exc.code}", "doc_ids": [], "text": ""}
        if "error" in reply or reply.get("result", {}).get("isError"):
            return {"denied": True, "error": short(reply.get("error", {}).get("message", reply)), "doc_ids": [],
                    "text": ""}
        hits = [h for c in reply["result"].get("content", []) for h in json.loads(c.get("text") or "[]")]
        return {"denied": False, "doc_ids": [h.get("doc_id") or Path(h.get("uri", "")).stem for h in hits],
                "text": " ".join(h.get("text", "") for h in hits)}

    def agent(self, query: str) -> dict:
        a = ask(self.url, bearer_token(self.w), query, background=True)
        sources = [s for r in a["tool_results"] for s in r.get("sources", [])]
        return {"answer": a["answer"], "doc_ids": a["kb_citations"] + [s.strip("[]").split(" p.")[0] for s in sources],
                "text": a["answer"], "cited": DOC in a["kb_citations"], "invocation_id": a["invocation_id"],
                "tools": a["tools"], "seconds": a["seconds"]}


def matrix(persona: str, paths: Paths, phase: str) -> list[dict]:
    jobs = [(q, path, tier) for q in SPEC["questions"] for path, tier in
            [("index", "finance"), ("index", "general"), ("mcp", "finance"), ("mcp", "general")]
            + ([("agent", None)] if paths.url else [])]

    def one(job) -> dict:
        q, path, tier = job
        out = paths.agent(q["question"]) if path == "agent" else getattr(paths, path)(tier, q["question"])
        row = {"phase": phase, "persona": persona, "path": path if tier is None else f"{path}:{tier}", "id": q["id"],
               "leaks": leaks(q, out["text"], out["doc_ids"]), "denied": out.get("denied", False),
               "got_finance_doc": DOC in out["doc_ids"]}
        row |= {k: out[k] for k in ("error", "answer", "cited", "invocation_id", "tools", "seconds") if k in out}
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, jobs))


def set_member(admin: WorkspaceClient, group: str, member_id: str, present: bool) -> None:
    """Add or remove one member of an account group, through the account SCIM API the workspace host proxies
    (the workspace SCIM API refuses: account groups "can only be managed in account"), as setup_identities.py does."""
    found = admin.api_client.do("GET", GROUPS_API, query={"filter": f'displayName eq "{group}"', "attributes": "id"})
    op = ({"op": "add", "path": "members", "value": [{"value": member_id}]} if present
          else {"op": "remove", "path": f'members[value eq "{member_id}"]'})
    admin.api_client.do("PATCH", f"{GROUPS_API}/{found['Resources'][0]['id']}",
                        body={"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [op]})


def wait_until(check, timeout_s: int = 900, every_s: int = 15) -> float | None:
    started = time.time()
    while time.time() - started < timeout_s:
        if check():
            return round(time.time() - started, 1)
        time.sleep(every_s)
    return None


def trace_check(admin: WorkspaceClient, agent_schema: str, rows: list[dict], timeout_s: int = 1200) -> dict:
    """Search every span of Ava's agent traces for the finance document and the forbidden facts."""
    ids = sorted({r["invocation_id"] for r in rows if r.get("invocation_id")})
    listed = ", ".join(f"'{i}'" for i in ids)
    query = f"""SELECT m.tags['invocation'], s.name, cast(s.attributes AS STRING)
                FROM {agent_schema}.copilot_trace_metadata m JOIN {agent_schema}.copilot_otel_spans s
                ON s.trace_id = m.trace_id WHERE m.tags['invocation'] IN ({listed})"""
    spans: list[list] = []

    def landed() -> bool:
        nonlocal spans
        spans = sql(admin, query)
        return {s[0] for s in spans if s[1] == "meridian-copilot"} >= set(ids)  # root spans end last

    waited = wait_until(landed, timeout_s, 30)
    facts = [f for q in SPEC["questions"] for f in q["forbidden_facts"]]
    hits = [{"invocation": s[0], "span": s[1], "found": [f for f in [*facts, DOC] if f in s[2]]} for s in spans]
    retrieval_tiers = sorted({t for s in spans if s[1] == "search_kb" for t in re.findall(r'\\?"tier\\?":\\?"(\w+)', s[2])})
    return {"invocations": len(ids), "traces_landed": len({s[0] for s in spans}), "spans_searched": len(spans),
            "seconds_waited": waited, "spans_with_finance_content": [h for h in hits if h["found"]],
            "retrieval_tiers_seen": retrieval_tiers}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    p.add_argument("--app", help="deployed copilot app (serves the prod schemas); omit to skip the agent path")
    p.add_argument("--skip-membership", action="store_true", help="do not remove and restore Ben's finance membership")
    args = p.parse_args()
    t = target_names(args.target)
    admin = WorkspaceClient()
    url = admin.apps.get(args.app).url if args.app else None
    ava, ben = WorkspaceClient(profile="meridian-ava"), WorkspaceClient(profile="meridian-ben")
    kb, agent = t.schemas["kb"], f"{t.catalog}.{t.schemas['agent']}"
    ava_paths, ben_paths = Paths(ava, t.catalog, kb, url), Paths(ben, t.catalog, kb, url)
    result: dict = {"task": "T19 leakage matrix", "target": args.target, "at": datetime.now(UTC).isoformat(),
                    "questions": len(SPEC["questions"]), "source_doc_id": DOC}

    rows = matrix("ava", ava_paths, "baseline") + matrix("ben", ben_paths, "baseline")
    if not args.skip_membership:
        ben_id, probe = ben.current_user.me().id, SPEC["questions"][0]["question"]
        try:
            set_member(admin, "meridian-finance", ben_id, present=False)
            result["seconds_until_index_refuses_ben"] = wait_until(lambda: ben_paths.index("finance", probe)["denied"])
            rows += matrix("ben", ben_paths, "after removal from meridian-finance")
        except Exception as exc:  # noqa: BLE001  record it; Ben is put back below either way
            result["membership_error"] = short(exc)
        finally:
            set_member(admin, "meridian-finance", ben_id, present=True)
        result["seconds_until_ben_restored"] = wait_until(lambda: not ben_paths.index("finance", probe)["denied"])
    result["rows"] = rows

    def where(persona: str, phase: str) -> list[dict]:
        return [r for r in rows if r["persona"] == persona and r["phase"] == phase]

    removed = where("ben", "after removal from meridian-finance")
    agent_rows = [r for r in where("ava", "baseline") if r["path"] == "agent"]
    result["trace_check"] = trace_check(admin, agent, agent_rows) if agent_rows else "not run (no --app)"
    ben_base = where("ben", "baseline")
    checks = {
        "Ava: zero leaks on every path": not any(r["leaks"] for r in where("ava", "baseline")),
        "Ava: the finance index refuses her (direct and MCP)": all(
            r["denied"] for r in where("ava", "baseline") if r["path"].endswith(":finance")),
        "Ben: the finance index answers him (direct and MCP)": all(
            r["got_finance_doc"] for r in ben_base if r["path"].endswith(":finance")),
        "Ben: cited answers from the agent": all(r.get("cited") for r in ben_base if r["path"] == "agent"),
    }
    if not args.skip_membership:
        checks["Ben removed and asked again"] = bool(removed) and "membership_error" not in result
    if removed:
        checks["Ben after removal: zero leaks on every path"] = not any(r["leaks"] for r in removed)
        checks["Ben after removal: the finance index refuses him"] = all(
            r["denied"] for r in removed if r["path"].endswith(":finance"))
        checks["Ben restored"] = result.get("seconds_until_ben_restored") is not None
    if isinstance(result["trace_check"], dict):
        tc = result["trace_check"]
        checks["traces: no finance chunk or fact entered Ava's model context"] = (
            tc["traces_landed"] == tc["invocations"] and not tc["spans_with_finance_content"]
            and "finance" not in tc["retrieval_tiers_seen"])
    counts = {}
    for r in rows:
        key = f"{r['phase']} | {r['persona']} | {r['path']}"
        c = counts.setdefault(key, {"asked": 0, "leaks": 0, "denied": 0, "finance_doc": 0, "cited": 0})
        c["asked"] += 1
        c["leaks"] += bool(r["leaks"])
        c["denied"] += r["denied"]
        c["finance_doc"] += r["got_finance_doc"]
        c["cited"] += bool(r.get("cited"))
    result["counts"], result["checks"] = counts, checks
    result["status"] = "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T19" / f"leakage_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    for key, c in counts.items():
        print(f"{key:<62} {c}")
    print(result["status"], json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
