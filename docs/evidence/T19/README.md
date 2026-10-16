# T19 permissions: leakage matrix (2026-10-17), PASS

`leakage_prod.json` (`tests/e2e/leakage_probe.py --target prod --app agent-bricks-meridian-copilot`). Six
finance-only questions (`config/leakage_questions.yaml`; every answer exists only in DOC-FEE-001, finance tier),
asked as Ava (support, general tier) and Ben (finance), each with their own credentials, on three paths:

- **agent**: the deployed copilot's invocation API.
- **index**: a direct query of each tier's AI Search index.
- **mcp**: the managed MCP server for AI Search (PREVIEW), the path Claude Code uses (T23).

A leak is a forbidden fact, or DOC-FEE-001, in anything Ava receives.

| Phase, persona | agent | index: finance | index: general | mcp: finance | mcp: general |
|---|---|---|---|---|---|
| Ava | 0 of 6 leaked; 6 abstained | 6 of 6 refused | 0 of 6 leaked | 6 of 6 refused | 0 of 6 leaked |
| Ben | 6 of 6 cited DOC-FEE-001 | 6 of 6 answered | no finance content (expected) | 6 of 6 answered | no finance content (expected) |
| Ben, removed from meridian-finance | 0 of 6 finance content | 6 of 6 refused | 0 of 6 | 6 of 6 refused | 0 of 6 |

Removal was made through the account SCIM API that the workspace host proxies. The finance index refused Ben
225 s after he was removed; his access was back 256 s after he was restored. These are single observations, not a
published latency.

**Trace check.** The six traces of Ava's agent calls landed in `meridian.agent.copilot_otel_spans`, 35 spans in
all: retrieval, every model input and output, and the answer. None contains DOC-FEE-001 or any forbidden fact,
and every retrieval span shows the general tier only. No finance chunk entered the model's context.

**Found and fixed.** In one post-removal call the copilot still read `meridian-finance` in Ben's group list (SCIM)
and queried the finance index. Unity Catalog had already revoked his access and refused the query, so nothing
leaked: the index grant caught a stale decision in our code. The refusal exception did crash that invocation,
giving an empty answer. Now a tier whose index refuses is dropped for the call (`meridian.kb.retrieve`), a refused
finance step stops a workflow run as not entitled, and a tool exception returns to the model as an error instead
of crashing the run.

**The limit, stated.** Row filters and column masks on a source table do not carry into an AI Search index. The
tiering here is a design we built (BUILD): one index per tier, Unity Catalog SELECT per index granted to the tier's
groups, and the agent's choice of indexes from the caller's own groups. The managed MCP server lists every index
in the schema to every caller (`tools/list`); the call itself is what Unity Catalog refuses.
