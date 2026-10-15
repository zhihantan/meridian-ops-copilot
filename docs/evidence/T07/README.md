# T07 local self-service development (2026-10-15)

| Done when | Status | Evidence |
|---|---|---|
| Local environment matches the target serverless version | PASS | `envs/serverless-v4` made by `databricks environments setup-local --serverless-version 4` (databricks-connect 17.3, remote package versions as constraints); jobs pin `environment_version: "4"` |
| Execution is remote | PASS | `connect_fay.json`: session `pyspark.sql.connect.session.SparkSession` on serverless, count of a gold table |
| Query found in `system.query.history` under the developer's identity | OPEN | marker query at 14:05 UTC not yet visible (latest row 14:09 UTC at the check); recheck |
| No data on the local machine | PASS | `tests/test_no_data_in_repo.py` (tracked data files, generator output, local Spark or Delta artifacts) |
| Parity table, each row tested | PASS | `docs/parity.md`, `parity.json`: 8 connect, 1 remote only (SDP), 3 not supported |
| Both environments hash identically | PASS (simulated) | Fay `uv sync` and a fresh copy installed by `scripts/install_from_lock.sh` (hash-checked): both `48dca3978fa0715d...`. The Codespace run waits for Gus's Codespaces secrets |

Findings:
- serverless environment 4 ships `databricks-sdk` 0.49; the admin tooling needs 0.70+, so the serverless-matched
  environment is a separate uv project rather than constraints on the repo root.
- `uv.lock` records the index URL; CI and Codespaces install from an export with `--require-hashes`.
- This laptop's package mirror withholds the fastapi version that serverless 4's `mlflow-skinny` 2.22 needs,
  so the MLflow parity row uses the tracking API through `databricks-sdk`.
