# T23 MCP and identity (2026-10-17), PASS

Claude Code, headless (`claude -p`), with the Databricks managed MCP servers in `examples/claude_code/mcp.json`:
- **AI Search** over `meridian.kb` (both tier indexes appear as tools), through the workspace endpoint. The docs
  now call it legacy: it bypasses Unity Gateway, and there is no Unity Gateway AI Search server.
- **Genie:** the "Meridian payments (gold)" space, through the workspace endpoint (legacy). Unity Gateway's
  `system.ai.genie_one_mcp` (GA) was tried. For Ava it "found nothing in the workspace for acq_7", and Ben's and
  Gus's sessions ended with empty answers after 10 to 11 tool calls.
- **Databricks SQL:** through Unity Gateway, `system.ai.dbsql` (Beta), so these calls also appear in Unity
  Gateway's own tables.

Each persona's session sends their own token. Built-in tools are off, so only MCP tools run, and the sessions load
no user hooks or plugins. Runner: `tests/e2e/mcp_personas.py`; evidence: `mcp_prod.json`.

| Prompt | Ava (support) | Ben (finance) | Gus (data engineer) |
|---|---|---|---|
| Refund approval threshold from the KB | SGD 500 from DOC-RB-021 (general); finance index refused | SGD 500 from DOC-RB-021 | both indexes refused: no knowledge tier |
| acq_7's failure rate yesterday (Genie) | answered: no rows for yesterday, data ends 2026-10-15 | same | no Genie tools: his group has no access to the space |
| Rows and latest ingestion in `meridian.bronze.payments` (SQL) | PERMISSION_DENIED | PERMISSION_DENIED | 34,511 rows, latest ingested 2026-10-15 12:56 |
| acq_2 bank transfer fee (finance index) | PERMISSION_DENIED; fee not in the answer | SGD 0.75 flat, cited DOC-FEE-001 | PERMISSION_DENIED |

The Genie answers show the synthetic data is a day old. The demo reset regenerates data anchored to the present.

**Per-user rows** (`usage_prod.json`, `scripts/collect_usage.py`, read after the calls):
- **`system.access.audit`.** `user_identity.email` gives the principal: a user name, or a service principal's
  application ID. `user_agent` gives the client, for example `claude-code/2.1.290` for Claude Code and an HTTP
  library for the probes. For MCP requests, `request_params.server_type` and `tool_name` give the server and tool.
  A refused MCP tool call is HTTP 200 with a JSON-RPC error, so it shows as an audit row with `error_message`
  "MCP request failed": every one of Ava's finance-index calls, and Ben's after he was removed from finance (T19).
- **`system.ai_gateway.usage`.** `requester` and `requester_type` give the principal and `user_agent` the client,
  with tokens and cache reads and writes per call. These are the copilot's calls, made as the caller: Ava, Ben and
  Eli each have their own rows.

In this workspace, MCP audit rows appeared within about 5 minutes and gateway usage within about 15. That is an
observation; there is no published latency, and no live demo step waits on these tables.

**Deviations:**
- **Identity is per-persona bearer tokens** (OAuth machine-to-machine for the persona service principals). Claude
  Code's OAuth flow for remote MCP servers would need an OAuth app registered at the account level, which this
  workspace cannot do.
- **Claude Code's own model calls are not made as the persona.** They follow this machine's managed settings: an
  organisation `apiKeyHelper` overrides `ANTHROPIC_AUTH_TOKEN` and cannot be changed per session. Pointing them at
  Unity Gateway failed with "400 Invalid Token", a misleading message. Two findings came out of testing that:
  - The gateway accepts only `Authorization: Bearer`; `x-api-key` gets a 401.
  - Claude Code's auto-mode beta header was also rejected.

  Per-user evidence for this path is therefore the MCP calls in the audit log. Per-user model usage comes from the
  copilot.

Statuses, from https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp (read 2026-10-17):
- `system.ai.genie_one_mcp` is generally available.
- `system.ai.dbsql`, `web_search` and `sandbox` are Unity Gateway Beta.
- The workspace endpoints (`/api/2.0/mcp/...`) are documented as legacy. They "bypass Unity Gateway. Their calls do
  not appear in Unity Gateway tracing tables, and they do not support MCP-level Unity Catalog grants, policies, or
  guardrails."

Unity Catalog still governs the data behind them: the finance index refused Ava and Gus, and SQL refused Ava and
Ben on bronze.
