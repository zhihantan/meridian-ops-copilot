# T27 cost and observability (2026-10-17)

**Prompt caching**, PASS (`cache_calls.json`, `scripts/cache_experiment.py`). Sixty calls, 30 with caching on and
30 off, through Unity Gateway. Each call has the copilot's own system prompt and tool definitions as its prefix
(identical every time) and a varying final message.

| Mode | Uncached input | Cache write | Cache read | Output | Median latency | List-price cost |
|---|---|---|---|---|---|---|
| Caching on | 2,820 | 1,538 (first call) | 44,602 (29 calls) | 90 | 0.90 s | $0.0193 |
| Caching off | 48,960 | 0 | 0 | 90 | 0.85 s | $0.0988 |

That is 80.5% less on this prefix, at list price.
- **Rates.** Claude Sonnet 5.5 on Databricks, in DBUs per million tokens: input 28.571, output 142.857, cache read
  2.857, cache write 35.714 (https://www.databricks.com/product/pricing/proprietary-foundation-model-serving,
  read 2026-10-17; regional processing adds 10%).
- **Price per DBU.** $0.07 for SKU `ENTERPRISE_ANTHROPIC_MODEL_SERVING`, from `system.billing.list_prices`.
- **Latency.** No gain at this prefix size (about 1,500 tokens).
- **Cross-check.** `system.ai_gateway.usage` has the same calls (61 rows in the window: these 60 and one other).
  Its cache reads (44,602) and writes (1,538) match the responses exactly. Its `input_tokens` counts cached tokens
  too, unlike the API response's `input_tokens`.
- **In production.** Across all 62 traced copilot runs, cache reads (204,178 tokens) exceeded uncached input
  (198,811).

**What the POC has cost**, from `system.billing.usage` at list price, 2026-10-13 to 2026-10-16 (`cost.json`,
`scripts/cost_report.py`). The workspace is shared with other projects, so only what is Meridian's is counted:
- **Jobs and pipelines tagged `project=meridian-poc`:** $25.28.
- **AI Search endpoint `meridian-search`:** $9.22.
- **Copilot app compute:** $4.30.
- **Model, Genie and pipeline usage run as Meridian's service principals:** about $2.50.
- **Counted total:** $41.29.
- **Shared SQL warehouse (estimate):** about $10.38 more. Meridian's statements were 1.4% of its execution time.
  That method undercounts the time the warehouse is kept warm between statements.
- **Not counted:** the presenter's own model and Genie calls, which mix projects, and other projects' endpoints.

**Observability views** over the copilot's traces in Unity Catalog (`sql/agent_views.sql`, applied by
`scripts/setup_traces.py`):
- `meridian.agent.v_copilot_runs`: one row per invocation, with caller, tiers, duration, model and tool calls, and
  tokens including cache.
- `meridian.agent.v_copilot_tool_latency`: the slowest tools. Genie has a median of 12.7 s and a 95th percentile of
  34.6 s; KB search a median of 2.0 s; a model call a median of 1.2 s.
- `meridian.agent.v_copilot_denials`: step guard and procedure refusals, index refusals, model safeguard refusals and
  errors.

**Dashboard as code.** "Meridian ops" (`resources/dashboards.yml`) has one definition. `scripts/gen_dashboard.py`
(`make gen-dashboard`) generates it per target with that target's names, and the bundle promotes it dev to
staging to prod. A page is included only where its tables exist:
- **Pipeline health:** acquirer status (degraded first), payments by market, and the issues of the last 14 days:
  failed runs and tasks, pipeline errors, check breaches and quarantine. Successful runs are left out.
- **Knowledge:** documents per tier, ingest failures, and who changed each document.
- **Copilot (prod only, where the traces are):** cache tokens, runs by caller, the slowest tools, refusals and
  denials. Callers are shown by persona, from the membership mirrors, so no principal ID or user name is in the
  definition.

Fixed on 2026-10-21:
- The page headers ran the heading and its description into one line.
- Callers showed principal IDs.
- The health table covered only 24 hours, which the 10-minute knowledge sweep filled, so a replayed incident
  dropped off it.

Viewers query with their own permissions (`embed_credentials: false`), so the market row filter and the masks
apply per viewer. Every dataset query of each target's definition was executed before deploying.

| Target | Pages |
|---|---|
| dev | Pipeline health, Knowledge |
| staging (2026-10-17) | Pipeline health. Staging's data comes from the CI integration run (the incident included), and it has no knowledge base. Its quality checks, gold refresh and views were run once so the page has data |
| prod | POC scorecard, Pipeline health, Knowledge, Copilot |

The knowledge provenance view (`v_kb_changes`) is in `sql/kb_views.sql`, applied by the audit export job. A target
without a knowledge base (staging) can then still create its pipeline views.
