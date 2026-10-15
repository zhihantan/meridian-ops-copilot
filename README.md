# Meridian Ops Copilot

A reference implementation on Databricks for a fictional marketplace, Meridian Commerce. All data is synthetic.

- **Governed pipelines:** contract-driven data quality with quarantine, PII detection and masking, drift and freshness alerts, lineage, and multi-developer CI/CD with rollback.
- **Permission-aware knowledge base:** incremental sync from several sources into one search index per access tier.
- **Ops agent:** a Claude tool loop that follows an approved runbook, queries data through Genie, asks a human before acting, and is reachable from Claude Code over MCP.

Items marked **BUILD** are custom code; items marked **PREVIEW** use Databricks features that are not yet generally available.

## Quick start
```bash
uv sync --all-groups
uv run pytest
make gen-data
```

## Guides
- `docs/onboarding.md`: local development (Databricks Connect on serverless) and a Codespace for a second developer
- `docs/cicd.md`: pull request checks, the integration test, staging and prod deploys, rollback
- `docs/runbooks/bad_backfill.md`: find a bad write, restore the serving table, recompute silver
- `docs/job_graph.md`: every job and pipeline with its triggers (generated from the bundle)
- `docs/parity.md`: what works from local code over Databricks Connect, tested
- `docs/evidence/`: proof per task, with PASS, FAIL or OPEN
