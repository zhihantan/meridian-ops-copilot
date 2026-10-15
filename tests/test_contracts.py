"""Contract rules scored against planted.json with DuckDB, no cluster needed (T03, T04, T09 gate).

A change that weakens a rule (for example allowing SGX as a currency) fails these tests in CI.
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from meridian.common import pii
from meridian.contracts.compiler import load_all
from meridian.synth import structured

ANCHOR = datetime(2026, 10, 22, 7, tzinfo=UTC)
DUCK_TYPES = {"STRING": "VARCHAR", "TIMESTAMP": "TIMESTAMPTZ"}


@pytest.fixture(scope="session")
def generated(tmp_path_factory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("synth")
    return out, structured.generate(ANCHOR, out)


@pytest.fixture(scope="session")
def contracts():
    return load_all()


def typed_view(contract, files: list[Path], tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """Load NDJSON as text, then TRY_CAST per the contract: unparseable values become NULL,
    like Auto Loader moving them to _rescued_data."""
    cols = [c["name"] for c in contract.schema]
    staging = tmp_path / f"{contract.dataset}.csv"
    with open(staging, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        for f in files:
            for line in f.read_text().splitlines():
                rec = json.loads(line)
                writer.writerow(["" if rec.get(c) is None else str(rec[c]) for c in cols])
    con = duckdb.connect()
    con.execute("CREATE MACRO regexp_like(s, p) AS regexp_matches(s, p)")
    casts = ", ".join(
        f"TRY_CAST(nullif({c['name']}, '') AS {DUCK_TYPES.get(c['type'], c['type'])}) AS {c['name']}"
        for c in contract.schema
    )
    con.execute(f"CREATE VIEW typed AS SELECT {casts} FROM read_csv('{staging}', all_varchar = true, header = true)")
    return con


def failed_rules(con, contract) -> dict[str, list[str]]:
    rows = con.execute(f"SELECT {contract.key}, {contract.failed_rules_sql('duckdb')} FROM typed").fetchall()
    return {key: sorted(rules) for key, rules in rows}


def test_contracts_compile(contracts):
    assert set(contracts) == {"payments", "customers"}
    payments = contracts["payments"]
    assert "amount DECIMAL(12,2)" in payments.schema_hints()
    assert payments.fail_expectations() == {"payment_id_not_null": "payment_id IS NOT NULL"}
    assert set(payments.routing_config()) == {"page", "slack_dq", "table_only"}


def test_bad_rows_quarantined_with_correct_rules(generated, contracts, tmp_path):
    out, planted = generated
    contract = contracts["payments"]
    con = typed_view(contract, [out / "payments/bad_rows/payments_bad_rows.json"], tmp_path)
    got = failed_rules(con, contract)
    expected = {e["payment_id"]: sorted(e["expected_rules"]) for e in planted["payments"]["bad_rows"]["quarantine_expected"]}
    for payment_id, rules in expected.items():
        assert got[payment_id] == rules, payment_id
    clean = {k for k in got if k not in expected}
    assert clean and all(got[k] == [] for k in clean)


def test_duplicates_detected(generated, contracts, tmp_path):
    out, planted = generated
    con = typed_view(contracts["payments"], [out / "payments/bad_rows/payments_bad_rows.json"], tmp_path)
    dupes = con.execute("SELECT payment_id FROM typed GROUP BY 1 HAVING count(*) > 1 ORDER BY 1").fetchall()
    assert [d[0] for d in dupes] == planted["payments"]["bad_rows"]["duplicate_payment_ids"]


def test_critical_rule_fails_exactly_once(generated, contracts, tmp_path):
    out, _ = generated
    contract = contracts["payments"]
    con = typed_view(contract, [out / "payments/critical/payments_critical.json"], tmp_path)
    (expr,) = contract.fail_expectations().values()
    assert con.execute(f"SELECT count(*) FROM typed WHERE NOT coalesce(({expr}), false)").fetchone()[0] == 1


def test_drift_rows_lose_amount(generated, contracts, tmp_path):
    out, planted = generated
    contract = contracts["payments"]
    con = typed_view(contract, [out / "payments/drift/payments_drift.json"], tmp_path)
    rules = con.execute(f"SELECT {contract.failed_rules_sql('duckdb')} FROM typed").fetchall()
    assert len(rules) == planted["payments"]["drift"]["rows"]
    assert all("amount_present" in r[0] for r in rules)


def test_relaxing_currency_releases_only_relaxable_rows(generated, contracts, tmp_path):
    out, planted = generated
    contract = contracts["payments"]
    relaxed_rules = [
        replace(r, expr=r.expr.replace("'USD')", "'USD', 'VND')")) if r.name == "currency_valid" else r
        for r in contract.rules
    ]
    relaxed = replace(contract, rules=relaxed_rules)
    con = typed_view(contract, [out / "payments/bad_rows/payments_bad_rows.json"], tmp_path)
    before, after = failed_rules(con, contract), failed_rules(con, relaxed)
    released = {k for k in before if before[k] and not after[k]}
    relaxable = {e["payment_id"] for e in planted["payments"]["bad_rows"]["quarantine_expected"] if e["relaxable"]}
    assert released == relaxable


def test_clean_history_has_no_false_positives(generated, contracts, tmp_path):
    out, _ = generated
    contract = contracts["payments"]
    files = sorted((out / "payments/incident").glob("*.json")) + sorted((out / "payments/baseline").glob("*.json"))[:2]
    con = typed_view(contract, files, tmp_path)
    assert con.execute(f"SELECT count(*) FROM typed WHERE len({contract.failed_rules_sql('duckdb')}) > 0").fetchone()[0] == 0


def test_card_numbers_in_notes_are_quarantined(generated, contracts, tmp_path):
    out, planted = generated
    contract = contracts["customers"]
    con = typed_view(contract, [out / "customers_changes/initial/customers_initial.json"], tmp_path)
    flagged = {k for k, rules in failed_rules(con, contract).items() if "notes_no_card_number" in rules}
    assert flagged == {x["customer_id"] for x in planted["customers"]["notes_card_quarantine"]}


def test_notes_redaction_recall(generated):
    out, planted = generated
    notes = {}
    for line in (out / "customers_changes/initial/customers_initial.json").read_text().splitlines():
        rec = json.loads(line)
        notes[rec["customer_id"]] = rec["notes"]
    planted_pii = planted["customers"]["notes_pii"]
    caught = sum(p["value"] not in pii.redact(notes[p["customer_id"]]) for p in planted_pii)
    assert caught / len(planted_pii) >= 0.95
    benign = [n for cid, n in notes.items() if n and cid not in {p["customer_id"] for p in planted_pii}
              and "card" not in n]
    assert all(pii.redact(n) == n for n in benign)
