# Known gaps (state them out loud)

Each gap is something the platform does not do natively, or that this POC does not demonstrate. Where we built
around it, the BUILD part is named, with its evidence.

## Platform gaps we built around

| Gap | What we did | Evidence |
|---|---|---|
| No managed Slack message connector (Slack is paused in this POC) | The knowledge base reads a Slack history export landed in a volume, the shape a puller writes (BUILD) | T10, T11 |
| No automatic quarantine table | Quarantine and severity routing are compiled from data contracts (BUILD) | T03 |
| No single graph of cross-job dependencies and triggers | Generated from the bundle YAML (BUILD) | T06 |
| Data Classification runs on a schedule, not instantly, and does not cover free text | ABAC keys on classification tags; manual tags are the fallback while a scan is pending; free text is redacted in the pipeline | T04 |
| Lineage is automatic, but a changelog is not; DML from a job into a streaming table is not a lineage write edge; lineage lags | A nightly lineage changelog (BUILD); table history names the writing job and run at once | T06, T06b |
| `RESTORE` is not supported on pipeline streaming tables | Recovery is a targeted delete and refresh, or a full refresh; RESTORE only on ordinary Delta tables | T06 |
| No one-click rollback; rolling back code does not roll back data | Redeploy a known-good tag, then reprocess | T09 |
| Row filters and column masks on a source table do not apply to AI Search indexes | One index per tier with Unity Catalog SELECT per index, and the agent picks indexes from the caller's groups (BUILD) | T13, T19 |
| Inside a SQL SECURITY DEFINER procedure, group functions check the owner, not the caller | Approver and entitlement checks compare `session_user()` with membership mirrors that an admin refreshes (BUILD). A mirror is stale until it is refreshed | T18 |
| Only workspace admins can read group membership | The membership mirrors are written by an admin-run governance step, not by the CI principal | T18 |
| A user's group list can lag Unity Catalog after a membership change | Unity Catalog's own index check refused the stale call; retrieval now drops a refused tier | T19 |
| Managed memory partitions entries by an actor ID the caller chooses, so the partition is not an access boundary; an agent binds one store | Actor, store and pointer-only finance facts are decided in code, and finance facts are re-fetched as the caller (BUILD) | T25 |
| Service policies (PREVIEW) decide per call and do not track multi-step state | Not attempted. Ordering, approval and arguments are enforced by the step guard and the definer procedures (BUILD) | T18 |
| The workspace MCP endpoints are documented as legacy: they bypass Unity Gateway's tracing and MCP-level grants | Data access stays under Unity Catalog. SQL moved to Unity Gateway's `system.ai.dbsql` (Beta). No Unity Gateway AI Search server exists, and Genie One (GA) did not find this space's data here | T19, T23, T24 |
| `tools/list` on the AI Search MCP shows every index to every caller | The call is what Unity Catalog refuses | T19 |
| OAuth for external MCP clients needs an account-level app registration, which this workspace cannot make | Per-persona bearer tokens | T23, T24 |
| System tables are not real-time and have no published latency | Scenes that need them are staged at least 3 hours before the demo (`scripts/reset_demo.py stage`) | T06, T23, T27 |
| Genie answers vary from run to run (rounding, baselines) | Curated example queries and explicit instructions; benchmarks re-run after each change | T22 |

## Limits of this POC

- **Previews.** Agent Bricks (the CLI, the durable agent server and memory stores), managed MCP, AI Search
  reranking and Unity Gateway's Beta MCP servers are PREVIEW or Beta, and may change.
- **Crash recovery.** Runs under request-user authorization cannot be recovered by the runtime. The copilot runs as
  its caller, so crash recovery (T26) is not demonstrated.
- **Claude Code's model calls.** On the presenter's laptop they follow organisation managed settings, so they are
  not made as the persona. Only the MCP calls carry the persona's token.
- **Cost.** The workspace is shared with other projects. The POC's cost counts only Meridian's own resources, and
  the shared SQL warehouse is an estimate.
- **Platform items not built.** No Databricks-hosted container registry (GHCR is used), no native Vault, no native
  video processing.
- **Not demonstrated:**
  - production data volumes and job counts (a small, config-driven pattern with generated jobs stands in);
  - streaming and continuous ingestion at volume;
  - cross-account networking;
  - multi-instance agent scaling;
  - a full-depth retrieval benchmark (the golden set is small, with dev and test splits).
