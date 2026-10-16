# Integration surfaces (T24)

How systems outside this repo reach Meridian's copilot, knowledge and data. Limits are quoted from Databricks
documentation read on 2026-10-17, with the URL. "Not collected" means the documentation we read states no limit.
Statuses are as the documentation shows them; PREVIEW and BUILD mark what is not GA or what we built.

| Surface | Use here | Auth | Documented limit | Source |
|---|---|---|---|---|
| Copilot invocation API (Agent Bricks `DurableAgentServer` on Databricks Apps, PREVIEW) | Ask the copilot: synchronous, streaming, or background with polling (`/api/invocations`, `/api/invocations/<id>`) | OAuth token of the caller; the Apps ingress passes a downscoped token to the agent, and every tool runs as the caller | 100 apps per workspace. Request timeout and payload size: not collected | https://docs.databricks.com/aws/en/resources/limits |
| Managed MCP, workspace endpoints (`/api/2.0/mcp/vector-search/...`, `/genie/...`, `/sql`) | Claude Code (T23), the external agent (T24) and the leakage probe (T19) | Bearer token of the caller; Unity Catalog applies to the data (index SELECT; Genie and SQL as the user) | Documented as legacy: "Legacy workspace endpoints bypass Unity Gateway. Their calls do not appear in Unity Gateway tracing tables, and they do not support MCP-level Unity Catalog grants, policies, or guardrails." Rate limits: not collected | https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp |
| Managed MCP through Unity Gateway (`/ai-gateway/mcp-services/system.ai.genie_one_mcp`, `system.ai.dbsql`) | The recommended path for Genie and SQL; both answer here | OAuth token of the caller | Genie One MCP generally available; dbsql, web_search and sandbox are Unity Gateway Beta. There is no AI Search MCP among them. Rate limits: not collected | https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp |
| AI Search (Vector Search) query API | The copilot's retrieval (per-tier indexes), queried with the caller's token | OAuth token; UC SELECT on each index | 500 endpoints per workspace; 50 indexes per endpoint; at most 200 results per hybrid query and 10,000 per ANN query | https://docs.databricks.com/aws/en/resources/limits |
| Genie Conversation API | `ask_genie` in the copilot, as the caller | OAuth token; CAN RUN on the space; queries run as the asker | 50 tables per space; 200,000 conversations per space; 10,000 messages per conversation. Poll every 1 to 5 s and stop after 10 minutes. Throughput: not collected | https://docs.databricks.com/aws/en/resources/limits; https://docs.databricks.com/aws/en/genie/conversation-api |
| SQL Statement Execution API | Workflow and correction procedures (`CALL`), membership mirrors, evidence scripts | OAuth token; CAN USE on the warehouse; EXECUTE on the procedures | `wait_timeout` 5 to 50 s; inline results over 25 MiB fail | https://docs.databricks.com/aws/en/dev-tools/sql-execution-tutorial |
| Unity Gateway, Anthropic path (`/ai-gateway/anthropic`) | The copilot's and the external agent's model calls, as the caller | Bearer token only (`x-api-key` gets 401, observed) | Pay-per-token Claude models other than Haiku 5.5: 1,000,000 input and 100,000 output tokens per minute, 360,000 queries per hour; 4 MB payload; 597 s per request | https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/limits |
| Agent Bricks memory stores (PREVIEW) | Per-user long-term memory (T25): mem-general, mem-finance | The app's own identity holds WRITE; our code sets the actor | Not collected | |
| Lakeflow Jobs | kb_sync (file arrival and a 10-minute sweep), exports, setup jobs | OAuth M2M (CI service principal) in staging and prod | 2,000 tasks running at once per workspace; 12,000 saved jobs. File-arrival trigger limits: not collected | https://docs.databricks.com/aws/en/resources/limits |
| System tables (`system.access.audit`, `system.ai_gateway.usage`, `system.billing.usage`) | Per-user evidence (T23), cost (T27) | SELECT on the system schemas | "No support for real-time monitoring. Data is updated throughout the day."; no published latency. Observed here: audit rows within about 5 minutes, gateway usage within about 15 | https://docs.databricks.com/aws/en/admin/system-tables/ |
| Exports volume (`/Volumes/<catalog>/obs/exports/`) | Dated log and audit files for external monitoring (T06b, T21) | Files API or a volume mount; READ VOLUME | Not collected | |

Notes:
- **OAuth for MCP clients.** Claude Code's sign-in flow for remote MCP servers needs an OAuth app integration,
  which is an account-level registration that this workspace cannot make. The runs here use per-persona tokens
  instead.
- **External agent.** `examples/external_agent/agent.py` uses no Databricks libraries: HTTPS to the MCP servers,
  and the Anthropic SDK pointed at Unity Gateway. It runs from any laptop with a token
  (`tests/e2e/external_agent_check.py`).
