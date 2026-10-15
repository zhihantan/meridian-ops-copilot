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
