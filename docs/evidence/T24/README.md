# T24 external agent and surfaces (2026-10-17), PASS

`examples/external_agent/agent.py` is a standalone Anthropic SDK tool loop with no Databricks libraries. It
lists the tools of the managed MCP servers over plain HTTPS, calls them with the caller's OAuth token, and
sends its model calls through the workspace's Unity Gateway with the same token.
`tests/e2e/external_agent_check.py` runs it outside the project, from a temporary folder, in an isolated
environment holding only the `anthropic` package (`uv run --isolated --no-project --with anthropic`).

`external_agent.json`: the same question, "What does acq_2 charge for a bank transfer payment, and above what
amount does a refund batch need approval?", asked as each persona:

| Persona | Fee (finance tier) | Threshold (general tier) |
|---|---|---|
| Ava | Refused: the finance index returned PERMISSION_DENIED, and the answer says so without guessing | SGD 500, cited DOC-REF-003 and DOC-RB-021; flags the older SGD 250 note as superseded |
| Ben | SGD 0.75 flat, cited DOC-FEE-001 | SGD 500, cited |

The persona tokens are minted with the Databricks SDK by the check, outside the agent. `databricks auth token`
serves only user (U2M) profiles; the personas are service principals with M2M profiles.

`docs/integration_surfaces.md` lists every surface: what it is used for here, how it authenticates, and its
documented limit. Each limit is quoted from the Databricks documentation, read on 2026-10-17, with the URL;
where the documentation gives no limit, the table says "not collected". One finding from reading the docs: the
workspace MCP endpoints used in T19, T23 and here are now documented as legacy. They still enforce Unity Catalog
on the data, but their calls bypass Unity Gateway's tracing and MCP-level grants. The recommended Unity Gateway
servers (`system.ai.genie_one_mcp` GA; `system.ai.dbsql` Beta) both answer here.
