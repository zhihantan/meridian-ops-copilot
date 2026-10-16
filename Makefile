# Meridian Ops Copilot: common commands. Bundle commands use DATABRICKS_CONFIG_PROFILE.
TARGET ?= dev
ANCHOR ?= now

.PHONY: sync test lint gen-data gen-corpus contracts-docs validate deploy run-pipeline land

sync:
	uv sync --all-groups

test:
	uv run pytest -q

lint:
	uv run ruff check src tests scripts

# Synthetic data and planted.json, with timestamps anchored to ANCHOR (default: now)
gen-data:
	uv run python -m meridian.synth.structured --anchor $(ANCHOR) --out data/out --evidence

gen-corpus:
	uv run --group synth python -m meridian.synth.corpus --anchor $(ANCHOR) --out data/out

contracts-docs:
	uv run python -m meridian.contracts.compiler --docs docs/contracts

validate:
	databricks bundle validate -t $(TARGET)

deploy: validate
	databricks bundle deploy -t $(TARGET)

run-pipeline:
	databricks bundle run -t $(TARGET) dlc

# make land BATCH=payments/incident
land:
	scripts/land.sh $(TARGET) $(BATCH)

.PHONY: gen-jobs
# Generated ingestion jobs from config/sources.yaml (T06c)
gen-jobs:
	uv run python scripts/gen_jobs.py

.PHONY: job-graph job-runs drill-evidence
# Cross-job graph from the bundle (T06, BUILD)
job-graph:
	uv run python scripts/job_graph.py --target $(TARGET)

# Recent runs and their trigger types, from the Jobs API (T06 evidence)
job-runs:
	uv run --group dbx python scripts/job_runs.py --target $(TARGET) --out docs/evidence/T06/triggers_$(TARGET).json

# Bad-backfill drill evidence: history, blast radius, restore, lineage (T06, read-only)
drill-evidence:
	uv run --group dbx python scripts/backfill_drill.py --target $(TARGET) --out docs/evidence/T06/drill_$(TARGET).json

.PHONY: land-kb kb-sync kb-drill
# Knowledge corpus into the landing volume by tier (T10, T11); kb_sync runs on file arrival (or kb-sync)
land-kb:
	scripts/land.sh $(TARGET) kb

kb-sync:
	databricks bundle run -t $(TARGET) kb_sync_job

# Incremental sync drill: rerun, edit, delete, re-add, full refresh (T12)
kb-drill:
	uv run --group dbx python scripts/kb_drill.py --target $(TARGET)

.PHONY: eval eval-retrieval eval-answers kb-failure-drill
# Golden-set evaluation (T16): retrieval ablation and abstention threshold, then judged answers
eval: eval-retrieval eval-answers

eval-retrieval:
	uv run --group dbx --group agent python scripts/eval_retrieval.py --target $(TARGET)

eval-answers:
	uv run --group dbx --group agent python scripts/eval_answers.py --target $(TARGET)

# Failure drill: corrupt file, unreachable source, silent drop (T15)
kb-failure-drill:
	uv run --group dbx python scripts/kb_failure_drill.py --target $(TARGET)
