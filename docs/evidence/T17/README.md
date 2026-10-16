# T17 agent (2026-10-16)

`agent-bricks-meridian-copilot` (Databricks App): an Anthropic SDK tool loop (`apps/copilot/copilot/loop.py`) on Agent
Bricks' managed `DurableAgentServer`, built with `scripts/build_copilot.sh` and deployed with `agentbricks deploy`.

| Done when | Status | Evidence |
|---|---|---|
| Deployed agent answers a KB question with citations as Ava and as Ben | PASS | `copilot_probe.json`: each persona calls with its own OAuth token; both get a cited general answer (refund approval, DOC-REF-003 / DOC-RB-021) |
| Finance content only for the entitled | PASS | Ben gets the acq_7 SLA credit cited to DOC-FEE-001; Ava gets "I don't have that in the knowledge base", and her search never touched the finance index |
| Sync, stream and background modes | PASS | sync returns the output; stream emits `run.started`, a `message` per step, `run.completed`; background returns `queued`, then `completed` on polling |

How identity works (no model judgment involved):
- `[auth.user] required = true`: the Apps ingress forwards each caller's own downscoped token
  (scopes `vector-search`, `ai-gateway`, `model-serving`, `sql`); the tools and the model call run as the caller.
  Without a caller token the invocation fails; there is no fallback to the app's identity.
- `search_kb` resolves the caller's tiers from their groups (`config/scenario.yaml` `knowledge_tiers`), queries only
  those indexes with the caller's token (Unity Catalog grants apply too), drops any off-tier hit, and abstains below the
  reranker threshold before the model sees anything.
- The system prompt and tool definitions carry `cache_control`; traces go to the app's MLflow experiment, tagged with
  the caller and their tiers.

Not yet wired: `ask_genie` (T22), workflow tools `get_workflow`, `log_step`, `refund_batch` (T18), memory (T25).
