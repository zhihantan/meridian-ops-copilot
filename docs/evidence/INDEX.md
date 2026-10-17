# Evidence index (T29)

One row per task: its status, where the proof is, the headline result, and how it departs from the plan.
Statuses: PASS, PARTIAL (some checks open), OPEN (blocked or not run), SKIPPED (optional, not done). Every folder
under `docs/evidence/<task>/` has the run outputs; platform findings are in `spikes.md`, UI-only steps in
`manual_steps.md`, and the gaps to state in `../known_gaps.md`.

| Task | Status | Evidence | Headline | Deviations |
|---|---|---|---|---|
| SM1, SM3 | PASS | `SM1/`, `SM3/` | Smoke tests on the workspace | |
| T01 | PASS | `databricks.yml`, `resources/` | Bundle with dev, staging, ci and prod targets | |
| T02 | PASS | `T02/planted_summary.json` | Synthetic data with planted issues, anchored to a time | 7 acquirers (acq_7 planted) |
| T03 | PASS | `T03/` | Quarantine and severity routing from contracts; 16/16 planted issues found on dev, staging and prod; reprocess idempotent; a critical rule fails the update | Quarantine is BUILD |
| T04 | PASS | `T04/` | ABAC masks and the market row filter by persona: probes PASS on dev and prod | The scan had tagged nothing after about 39 hours, so prod's tags come from the contracts (fallback); time-to-tag still measured on staging |
| T05 | PASS | `T05/` | Drift, freshness and coverage monitors on dev and prod | |
| T05b | PASS | `T05b/` | AI digest of quality issues; counts match | Alerts go to email and logs; Slack paused |
| T06 | PASS | `T06/` | FILE_ARRIVAL, TABLE and PERIODIC triggers in prod; bad backfill found through table history and lineage, recovered to 16/16 | Recovery is targeted delete and refresh (no RESTORE on streaming tables) |
| T06b | PASS | `T06b/` | Lineage changelog, centralized log views, dated log export | |
| T07 | PARTIAL | `T07/` | Development in the workspace: a Git folder, an isolated dev target per developer, deployed from the bundle UI; developers cannot write staging or prod | The timed first deployment from a Git folder is a rehearsal step. Local development and the Codespace were removed |
| T08 | PASS | `T08/` | Unity Catalog secrets: per-secret READ, rotation without redeploy, audit | |
| T09 | PARTIAL | `T09/` | Promotion inside the workspace: the staging integration job passes (16/16, about 6 min) and fails on a rule-weakening branch; only admins deploy staging and prod | GitHub holds the code only, because its runners cannot reach the workspace. The prod release and the rollback from a Git folder are rehearsal steps |
| T10 | PASS | `T10/` | Knowledge corpus by tier: files and a Slack history export | Slack is a synthetic export |
| T11 | PASS | `T11/` | Sources and connector status | No managed Slack connector |
| T12 | PASS | `T12/` | Incremental kb_sync: an edit touches one document, a delete removes its chunks, a full refresh rebuilds | |
| T13 | PASS | `T13/` | Per-tier AI Search indexes, SELECT per index | |
| T14 | PASS | `T14/` | Prod freshness with the 10-minute sweep: create 8.7, edit 5.3, delete 11.9 minutes (95th percentile) | File-arrival triggers miss edits and deletes, hence the sweep |
| T15 | PASS | `T15/` | Corrupt file skipped and logged, unreachable source fails clearly, reconcile names and repairs drift | |
| T16 | PASS | `T16/` | Hybrid search with the reranker is best; correctness 8/8 dev and 7/8 test; abstention 4/4 out of scope, 0/16 in scope | Small golden set (20 questions) |
| T17 | PASS | `T17/` | Copilot on Agent Bricks as a Databricks App; every tool runs as the caller; sync, stream and background | PREVIEW runtime |
| T18 | PASS | `T18/` | Governed RB-014: database drill 13 attacks refused (dev and prod), agent drill guard 19/19 and agent 11/11 (prod); zero unapproved refunds | Service policy not attempted; the memory attack ran in T25 |
| T19 | PASS | `T19/` | Leakage matrix on agent, index and MCP paths: 0 leaks; removal from finance enforced in 225 s; traces clean | |
| T20 | PASS | `T20/` | Corrections: 2 of 2 improved, rejected and unreviewed not served, no test regression, revert unserves in 48 s | Run on dev; prod has the procedures |
| T21 | PASS | `T21/` | Every cited document traces to version, editor, time and reason; daily audit export | View in the obs schema |
| T22 | PASS | `T22/` | Genie space as code, benchmarks 8/8; 8/8 mixed answers cite both Genie and the knowledge base | Two benchmark corrections recorded |
| T23 | PASS | `T23/` | Claude Code over MCP as Ava, Ben and Gus: different results per user; per-user rows in the audit log and gateway usage | Bearer tokens instead of OAuth; Claude Code's model route is the laptop's managed setting |
| T24 | PASS | `T24/`, `../integration_surfaces.md` | Standalone external agent over MCP, outside the project; surfaces with documented limits | |
| T25 | PASS | `T25/` | Two memory stores; 5 probes, 0 leaks; finance facts kept as pointers and re-fetched | PREVIEW memory stores |
| T26 | PARTIAL | `T26/` | Background runs with polling (T17 onward); workflow state survives in the database between invocations | Crash recovery not shown: request-user runs are never resumed, and every copilot run is one |
| T27 | PASS | `T27/`, `../../dashboards/` | Caching 80.5% cheaper at list price; POC cost from billing; trace views; the ops dashboard as code, deployed to dev, staging and prod | Staging has the pipeline page only (no knowledge base there) |
| T28 | SKIPPED | | Optional extras | |
| T29 | PARTIAL | this file, `../known_gaps.md`, `scripts/reset_demo.py`, `T29/health_check_2026-10-17.md` | Index, gaps, demo reset, and an asset health check with clean-up (dev 23, prod 22, staging 5 jobs; all latest runs pass) | Rehearsals on 21 Oct |
