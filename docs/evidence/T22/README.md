# T22 Genie and mixed questions (2026-10-16, curation 2026-10-17)

The Genie space "Meridian payments (gold)" is code: `config/genie_space.yaml` (three gold tables with descriptions, one
text instruction, six example queries, a `failure_rate_pct` measure, eight benchmarks with golden SQL), created and
updated by `scripts/setup_genie.py`; persona groups have CAN RUN, and Genie runs queries as the asking user.

| Done when | Status | Evidence |
|---|---|---|
| Benchmarks run (Genie's evaluation API) | PASS | `benchmarks_prod_before_curation.json`: 7/8 GOOD. The miss was our golden SQL: it returned a fraction while the space's instructions ask for percent. After fixing that benchmark, `benchmarks_prod.json`: 8/8 GOOD |
| `ask_genie` wired | PASS | the copilot asks Genie with the caller's own token (user scope `dashboards.genie`) and cites results as `[GENIE-<id>]`, keeping the Genie query and conversation IDs |
| At least 6 of 8 mixed answers carry both citation types | PASS, 8/8 | `mixed_prod.json`: asked as Ben through the deployed copilot (background invocations); every answer cites a Genie result and an expected knowledge-base document |
| Questions in another language (extra) | PASS on dev | `genie_language_dev.json` (`tests/e2e/genie_language_probe.py`): two questions asked in English and in Mandarin returned the same rows (acq_7 at 1.2% in both), and Genie replied in Mandarin although the space's instructions are English only. Dev had no degraded acquirer, so the first pair compares two empty results |

Notes: one Genie message failed during the first run (Genie returned FAILED); `ask_genie` now hands such failures to the
model as a tool error instead of failing the invocation. Mixed answers take 30 to 50 s, so long questions use background
invocations rather than a synchronous call.

Curation on 2026-10-17:
- **RB-014 example query.** The workflow's s1 question (T18) returned different baselines across runs (1.9% and
  2.8%), so a sixth example query now covers it, using the governed baseline in `acquirer_status`. The agent asks
  in that example's wording.
- **Baseline benchmark rounding.** The baseline benchmark then went to NEEDS_REVIEW twice. In the first run Genie
  rounded and the golden SQL did not; in the second, after the golden SQL was changed to round, Genie did not. The
  instructions now say explicitly that `acquirer_status` stores rates as fractions, shown as percentages with one
  decimal. With that, `benchmarks_prod.json` is 8/8 GOOD again. Genie's own run-to-run variation is the lesson:
  benchmarks are worth re-running after every curation change.
