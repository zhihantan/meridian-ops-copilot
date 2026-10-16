# T15 knowledge failures (2026-10-16)

| Failure injected | Visible within one cycle, with a readable reason | Evidence |
|---|---|---|
| Corrupt PDF lands | PASS: `kb.ingest_failures`: "ai_parse_document: Document conversion failed"; the run continues and other documents sync | `failures_dev.json`, run `219604965434645` |
| Source location unreachable | PASS: the run fails with `CF_PATH_DOES_NOT_EXIST_FOR_READ_FILES` and the job's failure email fires. Simulated by pointing the job at a missing folder; with Slack paused, a revoked bot token is not tested, and a revoked volume grant fails the same step with a permission error | run `1084759255933409` |
| Silent drop: a document removed from `kb.docs` with no source delete | PASS: the run's first task, `reconcile`, fails naming `DOC-RB-021` ("in the source but not live in kb.docs") and emails; the same run's sync repairs it | run `389607582864108`; `obs.kb_reconcile_events` |

Reconciliation (BUILD, `src/meridian/jobs/kb_reconcile.py`) compares the source, `kb.docs`, the chunk tables and the
indexes when nothing is pending, and treats documents with an ingest failure as known, not dropped.
