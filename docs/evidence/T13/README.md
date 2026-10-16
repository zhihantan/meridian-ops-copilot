# T13 indexes (2026-10-16)

| Done when | Status | Evidence |
|---|---|---|
| Both indexes online | PASS | `kb.idx_general` (33 chunks) and `kb.idx_finance` (2 chunks), Delta Sync with Databricks-managed embeddings (`databricks-gte-large-en`), bundle resources in `resources/kb_indexes.yml` (dev and prod) |
| Hybrid query returns results | PASS | `index_probe_dev.json`, `index_probe_prod.json` |
| Ava cannot query `idx_finance` | PASS | Ava (support) denied on `idx_finance`, allowed on `idx_general`; Ben (finance) and Eli (admin) allowed on both. Grants are UC `SELECT` on each index by tier, set in the bundle; the chunk tables themselves are granted to no persona group |

Sync is triggered, not continuous: the `sync_indexes` task of `meridian-kb-sync` starts it after each run, as the
job identity.
