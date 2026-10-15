# T06 prod bootstrap (2026-10-15)

| Step | Result |
|---|---|
| Landed 14 baseline payment files and 3 customer CDC files into the prod raw volume (18:10 SGT) | file-arrival trigger fired by itself: ingest run `354440852242979`, `trigger=FILE_ARRIVAL` |
| That run | FAILED: the CI principal lacked Run rights on the pipeline; fixed by granting it CAN_MANAGE in the bundle |
| Manual ingest run `64507441566324` (pipeline, then quality checks) as `meridian-ci` | SUCCESS, about 4.5 min |
| Redeploy | created `gold_refresh_job` (its table-update trigger needs `silver.payments` to exist: a fresh environment needs a two-step bootstrap) |
| Governance | ABAC policies and grants on catalog `meridian`; no manual tags, so classification time-to-tag is measured honestly |
| Quality monitors | table monitor on `meridian.silver.payments`, anomaly detection on `meridian.gold` |

Prod state after bootstrap: 32,200 payments (baseline only), 1,993 customers, 6 quarantined customer events,
0 drift breaches (no incident yet), a freshness breach ("no payments event for 1663 min"), and `secondary_email`
flagged as unprotected until Data Classification tags it.
