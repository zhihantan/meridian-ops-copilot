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
