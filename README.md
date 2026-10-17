# Meridian Ops Copilot

A reference implementation on Databricks for a fictional marketplace, Meridian Commerce. All data is synthetic.

- **Governed pipelines:** contract-driven data quality with quarantine, PII detection and masking, drift and freshness alerts, lineage, and promotion from dev to prod with an integration test and rollback.
- **Permission-aware knowledge base:** incremental sync from several sources into one search index per access tier.
- **Ops agent:** a Claude tool loop that follows an approved runbook, queries data through Genie, asks a human before acting, and is reachable from Claude Code over MCP.

Items marked **BUILD** are custom code; items marked **PREVIEW** use Databricks features that are not yet generally available.

## Where things run
Everything is developed and deployed in the Databricks workspace, from Git folders with the bundle UI. GitHub holds the code, assets and bundle. The presenter's tooling (tests, data generation, demo reset) runs with uv:
```bash
uv sync --all-groups
uv run pytest
make gen-data
```

## Guides
- `docs/onboarding.md`: develop in the workspace: a Git folder, your own dev target, the bundle UI
- `docs/cicd.md`: promotion inside the workspace: the integration job, admin deploys, rollback
- `docs/runbooks/bad_backfill.md`: find a bad write, restore the serving table, recompute silver
- `docs/job_graph.md`: every job and pipeline with its triggers (generated from the bundle)
- `docs/evidence/`: proof per task, with PASS, FAIL or OPEN
