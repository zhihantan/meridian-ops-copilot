# Spikes: things verified against the live workspace

| Date | Item | Finding |
|---|---|---|
| 2026-10-15 | ai_query batch inference with Claude | `databricks-claude-sonnet-5-5` and `-sonnet-5` are rejected ("not supported for batch inference"). `-sonnet-4-6`, `-sonnet-4-5` and `-haiku-4-5` work. The DQ digest pins `-sonnet-4-6`. Interactive calls through the gateway still use Sonnet 5.5. |
| 2026-10-15 | ai_query responseFormat | The DDL struct form is rejected for Claude endpoints; the JSON-schema form works. |
| 2026-10-15 | Serverless Python file tasks | `__file__` is not defined; jobs pass `--src-dir`. `.cache()` is not supported on serverless. |
| 2026-10-15 | RESTORE on streaming tables | Not supported (docs). Pipeline tables recover by refresh from bronze or reprocess. |
| 2026-10-15 | System tables | All readable here, including `system.ai_gateway.usage`. Observed lag: audit, lineage and query history 7-10 min; billing about 1h. |
| 2026-10-15 | Governed tags | Account tag-policy limit reached (3072), so no new governed tags. ABAC keys on Data Classification system tags (`class.*`, including `class.sg_nric`); the row filter reuses `row_scope=country`. |
| 2026-10-15 | Groups | The workspace SCIM API creates workspace-local groups (not usable in UC grants); account groups are created via the workspace-proxied account SCIM API. |
| 2026-10-15 | Catalogs on Default Storage | UI only; the API returns "Please use the UI to create a catalog with Default Storage". |
| 2026-10-15 | Auto Loader drift | When the drift file is present at the first schema inference, the new column is inferred instead of rescued; land the baseline first. |
