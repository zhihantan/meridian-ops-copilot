"""Execution is remote, so no table data belongs in the repo or the working tree (T07).

The only local data is the synthetic generator's output under data/ (gitignored, made by make gen-data).
Fails on tracked data files and on local Spark or Delta artifacts anywhere else.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA_SUFFIXES = {".parquet", ".delta", ".orc", ".avro", ".csv", ".jsonl", ".ndjson", ".pdf", ".docx", ".xlsx"}
ALLOWED_TRACKED = {"config/access_matrix.csv"}  # configuration, not data
LOCAL_SPARK_ARTIFACTS = ("spark-warehouse", "metastore_db", "derby.log", "_delta_log")
SKIP = {".git", ".venv", "data", "node_modules", ".ruff_cache", ".pytest_cache"}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def test_no_data_files_are_tracked():
    data = [f for f in tracked_files() if Path(f).suffix.lower() in DATA_SUFFIXES and f not in ALLOWED_TRACKED]
    assert not data, f"data files tracked in git: {data}"


def test_generator_output_is_not_tracked():
    assert not [f for f in tracked_files() if f.startswith("data/")]


def test_no_local_spark_or_delta_artifacts():
    found = []
    for path in REPO.rglob("*"):
        if SKIP & set(path.relative_to(REPO).parts):
            continue
        if path.name in LOCAL_SPARK_ARTIFACTS:
            found.append(str(path.relative_to(REPO)))
    assert not found, f"local Spark or Delta artifacts: {found}"
