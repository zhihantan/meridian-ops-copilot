"""Per-user rows for the agent and MCP paths (T23), from system tables. Read-only; run after the calls.

system.access.audit: managed MCP requests (service managedMcp), index queries (vectorSearch), Genie (aibiGenie) and
  SQL (databrickssql), with the caller (user_identity.email: a user name, or a service principal's application ID),
  the client (user_agent, e.g. claude-code/<version>), the MCP server type and tool, and the response status.
system.ai_gateway.usage: model calls through Unity Gateway with the requester, the client and the tokens,
  including cache reads and writes.
Both tables cover the whole account, so rows are filtered to this workspace. System tables are not real-time and
have no published latency: this reads a past window and records how many rows had landed. Principals are shown
as persona names. Writes docs/evidence/T23/usage_<target>.json.

    uv run --group dbx python scripts/collect_usage.py --since "2026-10-16 17:00:00" --until "2026-10-16 19:00:00"
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]
PERSONAS = {"ava": "meridian-ava", "ben": "meridian-ben", "gus": "meridian-gus"}
SERVICES = ("managedMcp", "vectorSearch", "aibiGenie", "databrickssql")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--since", required=True, help="UTC, e.g. '2026-10-16 17:00:00'")
    p.add_argument("--until", required=True)
    p.add_argument("--target", default="prod")
    args = p.parse_args()
    admin = WorkspaceClient()
    names = {WorkspaceClient(profile=prof).current_user.me().user_name: persona for persona, prof in PERSONAS.items()}
    names[admin.current_user.me().user_name] = "eli"
    ws = str(admin.get_workspace_id())
    params = {"ws": ws, "since": args.since, "until": args.until} | {f"p{i}": n for i, n in enumerate(names)}
    principals = ", ".join(f":p{i}" for i in range(len(names)))
    window = "workspace_id = :ws AND event_time BETWEEN to_timestamp(:since) AND to_timestamp(:until)"

    # A refused MCP tool call is HTTP 200 with a JSON-RPC error: the audit row carries an error_message.
    outcome = """CASE WHEN service_name = 'managedMcp' AND request_params['tool_name'] IS NULL THEN 'protocol'
                      WHEN response.error_message IS NOT NULL OR response.status_code >= 400 THEN 'refused or failed'
                      ELSE 'ok' END"""
    audit = sql(admin, f"""
        SELECT user_identity.email, service_name, action_name, split(user_agent, ' ')[0] AS client,
               request_params['server_type'] AS mcp_server, {outcome} AS outcome, count(*) AS calls
        FROM system.access.audit
        WHERE {window} AND user_identity.email IN ({principals}) AND service_name IN {SERVICES}
        GROUP BY ALL ORDER BY 1, 2, 3""", parameters=params)
    refused = sql(admin, f"""
        SELECT user_identity.email, service_name, coalesce(request_params['tool_name'], action_name),
               coalesce(response.error_message, cast(response.status_code AS STRING)), count(*)
        FROM system.access.audit
        WHERE {window} AND user_identity.email IN ({principals}) AND service_name IN {SERVICES}
          AND {outcome} = 'refused or failed'
        GROUP BY ALL ORDER BY 1, 2, 3""", parameters=params)
    gateway = sql(admin, f"""
        SELECT requester, requester_type, endpoint_name, split(user_agent, ' ')[0] AS client, status_code,
               count(*) AS calls, sum(input_tokens), sum(output_tokens),
               sum(token_details.cache_read_input_tokens), sum(token_details.cache_creation_input_tokens)
        FROM system.ai_gateway.usage
        WHERE {window} AND requester IN ({principals})
        GROUP BY ALL ORDER BY 1, 3""", parameters=params)

    def who(principal: str) -> str:
        return names.get(principal, "other")

    result = {
        "task": "T23 per-user rows in system tables", "target": args.target, "at": datetime.now(UTC).isoformat(),
        "window_utc": [args.since, args.until],
        "identify": {"system.access.audit": "user_identity.email (principal), user_agent (client), "
                                            "request_params.server_type and tool_name (MCP server and tool)",
                     "system.ai_gateway.usage": "requester and requester_type (principal), user_agent (client), "
                                                "endpoint_name, token_details (cache tokens)"},
        "audit": [{"persona": who(r[0]), "service": r[1], "action": r[2], "client": r[3], "mcp_server": r[4],
                   "outcome": r[5], "calls": int(r[6])} for r in audit],
        "refused_or_failed": [{"persona": who(r[0]), "service": r[1], "tool_or_action": r[2], "error": r[3][:120],
                               "calls": int(r[4])} for r in refused],
        "gateway": [{"persona": who(r[0]), "requester_type": r[1], "endpoint": r[2], "client": r[3], "status": r[4],
                     "calls": int(r[5]), "input_tokens": int(r[6] or 0), "output_tokens": int(r[7] or 0),
                     "cache_read_tokens": int(r[8] or 0), "cache_creation_tokens": int(r[9] or 0)} for r in gateway],
    }
    personas_in_audit = {r["persona"] for r in result["audit"] if r["service"] == "managedMcp"}
    result["checks"] = {"MCP calls attributed per persona": {"ava", "ben", "gus"} <= personas_in_audit,
                        "Ava's finance index calls are refused in the audit log": any(
                            r["persona"] == "ava" and "idx_finance" in str(r["tool_or_action"])
                            for r in result["refused_or_failed"]),
                        "gateway calls attributed per persona": len({r["persona"] for r in result["gateway"]}) >= 2}
    result["status"] = "PASS" if all(result["checks"].values()) else "NOT COLLECTED YET"
    out = REPO / "docs" / "evidence" / "T23" / f"usage_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    for section in ("audit", "refused_or_failed", "gateway"):
        for r in result[section]:
            print(section, r)
    print(result["status"], result["checks"])


if __name__ == "__main__":
    main()
