# T14 edit and delete timing (2026-10-16)

`meridian-kb-freshness-probe` (prod, job run `1115883605232320`, live triggers) wrote a canary document and a canary
Slack history page, then timed each change from the source write until the general index reflected it. Results in
`eval.freshness_runs` and `freshness_prod.json`.

Seconds from source write to index, runs 2 to 5 (4 runs, so p95 is close to the maximum):

| Source | Create p50 / p95 | Edit p50 / p95 | Delete p50 / p95 |
|---|---|---|---|
| Volume files | 355 / 518 | 217 / 315 | 623 / 710 |
| Slack pages | 355 / 519 | 218 / 315 | 623 / 714 |

Every phase is within the proposed p95 target of 15 minutes, and after each delete the index returned no rows for the
canary (zero stale hits after the window). Agent answers are checked again after T17.

What we found: a file-arrival trigger fires on **new files only**; overwrites and deletes start nothing (documented
behaviour). Run 1 began before we added the fix: its edit timed out at 20 minutes and its delete took 1,110 s. The fix
is `meridian-kb-sweep`, a 10-minute schedule that runs the same queued `kb_sync` job; creates still use file arrival.
Creates are slower than edits here because file arrival waits for 60 s of quiet and then queues behind sweep runs.
