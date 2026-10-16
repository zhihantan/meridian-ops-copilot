"""config/access_matrix.csv parses cleanly: an unquoted comma would shift a row's columns and skip it silently."""

import csv
from pathlib import Path

MATRIX = Path(__file__).resolve().parents[1] / "config" / "access_matrix.csv"
TARGETS = {"dev", "staging", "ci", "prod"}
TYPES = {"CATALOG", "SCHEMA", "TABLE", "SECRET", "VOLUME", "FUNCTION"}


def test_every_row_has_exactly_the_header_columns():
    with open(MATRIX) as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for line, row in enumerate(rows, start=2):
        assert None not in row, f"line {line}: more fields than the header (unquoted comma?)"
        assert all(v is not None for v in row.values()), f"line {line}: fewer fields than the header"
        assert row["securable_type"] in TYPES, f"line {line}: {row['securable_type']}"
        assert not row["targets"] or set(row["targets"].split(",")) <= TARGETS, f"line {line}: {row['targets']!r}"
        assert row["privileges"] and row["principal"], f"line {line}"
