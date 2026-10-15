# Meridian Ops Copilot POC: rules for Claude Code

Build spec: `Meridian_Ops_Copilot_2Day_Build_Spec.md`; execution plan: `private/PLAN.md`. Both are local only (gitignored). This repo is public: never commit customer names, customer requirement text, sizing numbers, scoring rubrics or workspace hostnames.

## Rules
- Work in task order (T01 to T29). Verify anything marked ⚠ in the spec against current Databricks docs and log it in `docs/evidence/spikes.md`.
- Label PREVIEW and BUILD in code comments, UI text and docs. Never present custom code as a native feature.
- Never hard-code secrets, prices, limits or benchmark numbers. Cite URL and date, or write "not collected".
- Bundles and SQL for everything with an API. Log UI-only steps in `docs/evidence/manual_steps.md` with the date.
- Serverless only. Fixed seeds. Tiny data. Every task writes `docs/evidence/<task>/` with PASS or FAIL.
- Security decisions (tier, user, approval) live in code or UC functions, never in model judgment.
- ABAC policies must EXCEPT the pipeline and index-sync service principals.

## Platform constraints (verified 15 Oct 2026)
- `RESTORE TABLE` is not supported on SDP streaming tables. Recover pipeline tables with rollback plus reprocess, a full refresh, or pipeline rewind (PREVIEW). RESTORE only ordinary Delta tables.
- System tables (lineage, audit, query history, billing, gateway usage) are not real-time and have no published latency. Never script a live demo step that waits on them; create the events hours ahead.
- The workspace sits on a shared regional metastore: no metastore or account admin. Account-level steps (federation policies, OAuth app registration, account previews) need a fallback.
- Reset demo state by rewriting data (pipeline full refresh, MERGE, INSERT OVERWRITE), never by dropping tables. Dropping loses tags, grants, masks, monitors and index sync.

## Layout
- `config/scenario.yaml`: shared constants. Data, corpus, workflows and golden set must agree with it exactly.
- `contracts/*.yaml`: single source of truth for schema hints, expectations, severity, routing and quarantine rules.
- `src/meridian/`: generators, contract compiler, pipeline and job code.
- `resources/`: bundle resources. `resources/generated/` is written by `make gen-jobs`.
- `docs/evidence/<task>/`: proof per task.

## Commands
- `uv sync --all-groups`, then `uv run pytest`
- `make gen-data` regenerates synthetic data and `planted.json` (timestamps anchored to now)
- Bundle commands use the CLI profile in `DATABRICKS_CONFIG_PROFILE` (see `private/PLAN.md`)
