# T12 kb_sync (2026-10-16)

| Done when | Status | Evidence |
|---|---|---|
| A second run reprocesses only changed documents, with counts logged | PASS | `drill_dev.json` (`scripts/kb_drill.py`): rerun 0 chunks written; edit of DOC-RB-009 changed 1 document (revision 2, 1 chunk replaced); source delete removed its chunk; re-add continued at revision 3; counts per run in `kb.sync_runs` |
| Full refresh works | PASS | same drill: `full_refresh=true` reprocessed all 33 documents and rewrote all 35 chunks |
| Event-driven | PASS | prod: landing the corpus fired `meridian-kb-sync` by file arrival (run `767000514887209`): 33 new documents, 35 chunks, 0 failures |

Design (BUILD): `kb.v_source_docs` → content hash per document → `ai_parse_document` (format 2.0) for PDF and DOCX,
text as-is → chunks of about 500 tokens per page with title and section → `kb.chunks_general` and
`kb.chunks_finance` (Change Data Feed on, stable chunk IDs) → index sync. Per-document failures go to
`kb.ingest_failures` and keep the previous chunks; `kb.sync_status` shows the last run, live documents and chunks
per tier and failures in the last 24h.
