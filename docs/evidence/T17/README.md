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

**Chat page (2026-10-21), BUILD.** Opening the app's URL in a browser returned `{"detail":"Not Found"}`: the server
had only the invocation API. `/` now serves `apps/copilot/runtime/chat.html`, which calls that API from the browser
(background, with the event stream for each step) and shows the steps, the answer and its citations. The Apps ingress
signs the visitor in and forwards their token, so the copilot runs as them. Answers are escaped before formatting.
- **Same packages.** The redeploy set `exclude-newer` to the previous deploy's time (2026-10-16 19:42 UTC):
  databricks-agentbricks 0.6.0 came out an hour after it. The app reused its environment; only its own code was rebuilt.
- **Nothing else changed.** The deployed `app.yaml` is identical to the previous deploy's. The other code differences are
  job modules added since then, which the copilot does not import.
- **Checked:** `/` returns the page (200, HTML). A question sent the way the page sends it ran
  `run.started`, a tool call, its result, the answer and `run.completed` in 16 s, citing DOC-RB-014. The page itself
  was tested against a local stand-in: steps, follow-ups, errors, a new conversation, and escaped markup.
