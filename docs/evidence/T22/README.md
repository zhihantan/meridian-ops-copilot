# T22 Genie and mixed questions (2026-10-16)

The Genie space "Meridian payments (gold)" is code: `config/genie_space.yaml` (three gold tables with descriptions, one
text instruction, five example queries, a `failure_rate_pct` measure, eight benchmarks with golden SQL), created and
updated by `scripts/setup_genie.py`; persona groups have CAN RUN, and Genie runs queries as the asking user.

| Done when | Status | Evidence |
|---|---|---|
| Benchmarks run (Genie's evaluation API) | PASS | `benchmarks_prod_before_curation.json`: 7/8 GOOD. The miss was our golden SQL: it returned a fraction while the space's instructions ask for percent. After fixing that benchmark, `benchmarks_prod.json`: 8/8 GOOD |
| `ask_genie` wired | PASS | the copilot asks Genie with the caller's own token (user scope `dashboards.genie`) and cites results as `[GENIE-<id>]`, keeping the Genie query and conversation IDs |
| At least 6 of 8 mixed answers carry both citation types | PASS, 8/8 | `mixed_prod.json`: asked as Ben through the deployed copilot (background invocations); every answer cites a Genie result and an expected knowledge-base document |

Notes: one Genie message failed during the first run (Genie returned FAILED); `ask_genie` now hands such failures to the
model as a tool error instead of failing the invocation. Mixed answers take 30 to 50 s, so long questions use background
invocations rather than a synchronous call.
