# Run of show (45 minutes)

About 25 minutes on the data lifecycle (scenes 0 to 4), 20 on the copilot and trust (scenes 5 to 7). Personas:
- **Ava:** support, general tier.
- **Ben:** finance.
- **Eli:** admin and approver, played by the presenter.
- **Fay:** developer, played by the presenter.
- **Gus:** a data engineer's service principal, used for Claude Code over MCP (scene 6).

Every scene has evidence from a run in `docs/evidence/`.

Where a scene acts as a persona:
- **Eli:** the presenter, signed in to the workspace UI.
- **Ava, Ben and Gus:** service principals, which cannot sign in to the UI. Ask the copilot as them from a terminal: `uv run --group dbx --group agent python scripts/ask.py --as ben "..."`. Follow-ups continue the conversation; `--new` starts over.
- **Ava versus Eli on the same rows (scene 2):** `uv run --group dbx python scripts/probe_personas.py --target prod`.

## Before the day

| When | Do | Check |
|---|---|---|
| Demo morning, first | `uv run --group dbx --group agent python scripts/reset_demo.py reset --target prod --yes`: fresh data anchored to now, baseline landed, pipeline and knowledge rebuilt, workflow and memory state cleared | `reset_demo.py check --target prod` passes |
| At least 3 hours before | `reset_demo.py stage --target prod --yes`: the bad backfill (scene 3), Claude Code over MCP as each persona (scene 6), the caching calls (scene 7), so system tables hold them | `scripts/collect_usage.py` shows the MCP rows; the lineage query in `docs/runbooks/bad_backfill.md` shows the backfill |
| At least 1 hour before | On staging, run `meridian-integration-test` on a rule-weakening branch, then on `main` (scene 4). Each run takes about the time measured in `docs/evidence/T09/` | One failed run and one passing run in the job's history |
| Before leaving | VPN on: the workspace has an IP access list | The copilot answers a test question |

## Scenes

| # | Minutes | Scene | Do | Evidence |
|---|---|---|---|---|
| 0 | 5 | Security architecture | Serverless egress, private connectivity, ingress, audit (slides) | `docs/known_gaps.md` |
| 1 | 6 | Detect | Land the incident live: `scripts/land.sh prod payments/incident`. Show the file-arrival run of `meridian-ingest`: one run holds the pipeline, the quality checks, the escalation and the AI digest. Then the quarantine counts and the dashboard's Pipeline health page | T03, T05, T05b, T06 |
| 2 | 4 | Protect | Ava and Eli query the same rows: masked, restricted, redacted. The market row filter applies in the dashboard, which each viewer queries as themselves. Genie applies the same policies to whoever asks, shown in `T04/genie_probe_dev.json`. The demo's Genie space holds only gold aggregates, with no customer or market columns, so there is nothing to mask or filter there | T04, T22 |
| 3 | 5 | Root cause | Table history names the backfill job and run. Lineage and the job graph give the blast radius. Recover with the targeted refresh | T06, `docs/runbooks/bad_backfill.md` |
| 4 | 8 | Ship a fix | Fay, in her Git folder, deploys her own dev copy from the bundle UI, runs it, pushes a branch and opens a pull request. Show the staged failed run of `meridian-integration-test` on a rule-weakening branch, then the passing run on `main`. Eli deploys `main` to prod from a Git folder (only admins can) and runs `meridian-post-deploy`, which records the release. To roll back, he deploys the previous tag | T07, T09 |
| 5 | 8 | The copilot works the incident | As Ben: "acq_7 is degraded. Run RB-014 for acq_7 over the last 24 hours". s1 to s5 run in order, with Genie and the SLA clause cited, and stop for approval. Eli approves in SQL (`CALL meridian.agent.approve_refund(...)`). Ben continues and s6 executes. As Ava: the same request stops at s2 (escalate to Finance) | T17, T18, T22 |
| 6 | 5 | Claude Code over MCP; memory | The same prompts as Ava, Ben and Gus give different results. Ben saves a finance fact; Ava cannot recall it | T19, T23, T25 |
| 7 | 4 | Trust and cost | The dashboard's Copilot page: traces as tables, slowest tools, denials. Then caching on and off, the retrieval ablation, the audit export, and the gaps slide | T16, T21, T27, `docs/known_gaps.md` |

## Fallbacks

- **The copilot is slow or a step times out.** Use background invocations (`meridian.agent.client.ask(..., background=True)`).
  The trace still shows the steps.
- **System-table rows have not landed.** Show the evidence JSON from the staged run, and say why: system tables
  are not real-time.
- **Genie varies.** The RB-014 s1 question matches a curated example. For free-form questions, show Genie's SQL.
