#!/usr/bin/env bash
# Integration test on a deployed target (T09): fresh synthetic data, the demo's landing order, the
# pipeline, then score_pipeline.py against planted.json. Any FAIL exits non-zero, so a change that
# weakens a contract rule fails here.
#   scripts/ci_integration.sh <target>      (ci for pull requests, staging after a merge)
set -euo pipefail
target="${1:?target}"
cd "$(git rev-parse --show-toplevel)"
export DATA_DIR="data/ci/${target}"   # its own generator output; data/out stays as dev and prod were landed
uv run python -m meridian.synth.structured --anchor now --out "$DATA_DIR"
eval "$(uv run python scripts/volumes.py "$target")"
for dataset in payments customers_changes; do
  databricks fs rm -r "dbfs:${RAW}/${dataset}" >/dev/null 2>&1 || true   # previous run's files
done
for batch in payments/baseline customers_changes/initial customers_changes/changes_1 customers_changes/changes_2; do
  scripts/land.sh "$target" "$batch" >/dev/null
done
databricks bundle run -t "$target" dlc --full-refresh-all >/dev/null   # baseline first: drift is rescued, not inferred
for batch in payments/incident payments/bad_rows payments/drift; do
  scripts/land.sh "$target" "$batch" >/dev/null
done
databricks bundle run -t "$target" dlc >/dev/null
uv run --group dbx python scripts/score_pipeline.py --target "$target" --planted "$DATA_DIR/planted.json"
