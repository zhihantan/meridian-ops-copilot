# Asset health check and test runs (2026-10-20 evening), PASS; the prod reset is open

Every bundle resource, and the assets outside the bundle, were checked in dev, staging and prod. Dev and staging got
test runs; prod was checked read-only, because its reset is a production change that the presenter runs.

## Configuration

| Check | Result |
|---|---|
| `bundle validate` | dev, staging and prod OK. Dev warned that the developer's CAN_MANAGE on their own dev folder was not in the bundle. Dev's permissions now name the developer, so a deploy from the bundle UI shows no warning. That entry is the only change in dev's resolved configuration; the redeploy changed no resource |
| `bundle plan` | Nothing to add, change or delete on any target (dev 40, staging 18, prod 40 unchanged): the workspace matches `main` |
| Code | No job, pipeline, app or config change since the prod deploy (4298b30). Unit tests 46 passed; lint clean |
| Copilot app | The running snapshot (deployed 2026-10-16) has the same copilot code as `main`. `app.yaml` differs only in formatting and the variables the deploy adds |

## Run history since 2026-10-18 (Jobs API)

| Target | Result |
|---|---|
| prod | No failed run. SUCCESS: `meridian-daily` 4 of 4, `meridian-ingest-sources` 62 of 62, `meridian-kb-sweep` and `meridian-kb-sync` 411 of 411 each, `meridian-post-deploy` 1. `meridian-ingest` 1 run, SUCCESS_WITH_FAILURES as designed (its checks flag the planted incident, the stale data and the untagged `secondary_email`) |
| dev, staging | No runs before the test runs below: development mode pauses dev's triggers, and staging only runs its integration job |
| Pipelines | All three IDLE, latest update COMPLETED |

## Test runs

| Target | Run | Result |
|---|---|---|
| staging | `meridian-integration-test` | SUCCESS: all 10 tasks, 16 of 16 planted defects, 6.8 minutes (`T09/integration_main_2026-10-20.json`) |
| dev | `meridian-ingest` | SUCCESS_WITH_FAILURES as designed. Only the freshness check failed, on dev's 5-day-old data. The pipeline, drift and PII coverage checks, escalate and digest succeeded. With no Slack secret, escalate and digest wrote to the job log |
| dev | `meridian-daily`, `meridian-ingest-sources`, `meridian-post-deploy`, `meridian-kb-sweep` (and the `meridian-kb-sync` run it starts), `meridian-acquirer-status` | SUCCESS |
| dev | `scripts/reset_demo.py reset --target dev --yes` | 15 minutes, every step succeeded: `meridian-demo-reset`, the baseline landing, a full refresh, the gold rebuild, governance, the knowledge landing and a full sync. Then `check --target dev`: 11 of 11 ok |
| dev | Scene 3 drill | Every step succeeded, in 5 minutes: the bad backfill; gold rebuilt from it; `meridian-recover` restoring gold to the version before it (the restore branch ran, reprocess was excluded); a selective full refresh of `silver.payments` from bronze; gold rebuilt; then `meridian-recover` reprocess (restore excluded). `scripts/backfill_drill.py --target dev`: PASS (the bad write was found in history, the corrupted day was recovered, gold was restored). Readiness afterwards: 11 of 11 ok |

## Read-only checks

| Asset | Result |
|---|---|
| Dashboards | Every dataset query of the three "Meridian ops" dashboards runs: dev 5, staging 3, prod 11. "Pipeline health, last 24h" was empty in dev and staging only because nothing had run there that day |
| Copilot | As Ben, 36 s: acq_7 from Genie, and the finance SLA terms from `DOC-FEE-001`. As Ava, 13 s: no finance clause, and a pointer to Finance |
| Scene 2 | `scripts/probe_personas.py --target prod`: PASS. Ava sees masked contacts and her home market only; Ben sees every market, masked; Eli sees raw values |
| AI Search | Endpoint online. The general (33) and finance (2) indexes are ready in dev and prod |
| Quality monitors | dev and prod `silver.payments`: active, and the hourly refreshes succeed. Anomaly detection is on both gold schemas. Staging has none, by design |
| Other | Genie spaces for dev and prod are present. The serving endpoints for the copilot, the digest model and the embeddings are ready. The SQL warehouse is running. The trace experiment `meridian-copilot-uc` is active, and both memory stores exist |
| Prod triggers | The file-arrival triggers (`meridian-ingest`, `meridian-kb-sync`) and the table-update trigger (`meridian-acquirer-status`) are configured and unpaused. They last fired on 15 and 16 Oct, before the consolidation |
| Prod reset permissions | `meridian-ci` owns every table that `meridian-demo-reset` rewrites, and it has ALL_PRIVILEGES on prod's landing volume, as in staging. Queueing is on for every job the reset runs |

## Open: the prod reset

`meridian-demo-reset` has never run in prod. It was not run here, because the reset is a production change; the
presenter runs it. Prod's readiness check passes 6 of 10. The 4 failures are what the reset clears:
- the data is anchored to 15 Oct;
- the incident from testing is still landed;
- there are workflow runs from testing;
- there are 3 memory entries.

`reset_demo.py check` now also confirms, on prod, scene 1's chain: the live triggers fired after the reset (the
baseline landing ran `meridian-ingest`, and its write rebuilt gold).

## Observations

- **Knowledge sweep load.** The 10-minute sweep accounts for 288 of prod's 313 job runs a day (6.4 hours of
  serverless job time) and for most of "Pipeline health, last 24h". It is the design behind T14's freshness
  numbers. Pausing `meridian-kb-sweep` after the demo stops it.
- **Data anchor.** The dev reset regenerated the local data, now anchored to 20 Oct. Prod's tables stay anchored to
  15 Oct until prod is reset.
