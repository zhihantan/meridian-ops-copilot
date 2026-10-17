"""Score a pipeline's tables against planted.json (T03 to T05; the T09 integration test).

Every planted defect must land where the contract says: quarantined with the right rule, deduplicated, rescued,
redacted, or applied as CDC. Shared by scripts/score_pipeline.py (SQL warehouse, from a laptop) and the
integration job (Spark, inside the workspace). `query` returns rows with every value as a string or None, as the
SQL Statement API does.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

Query = Callable[[str], list[list]]
Table = Callable[[str, str], str]
ALL_BATCHES = "baseline,incident,bad_rows,drift"


def in_list(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def fingerprint(value) -> str:
    """Stable, non-reversible stand-in for a value, so evidence can show equality without the data."""
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def score(planted: dict, t: Table, sql: Query, landed: str = ALL_BATCHES, echo: Callable[[str], None] = print
          ) -> list[dict]:
    pay, cust = planted["payments"], planted["customers"]
    results: list[dict] = []

    def check(task: str, name: str, expected, actual, pii: bool = False) -> None:
        """Record one check; values that are (synthetic) personal data go to the evidence as hashes."""
        ok = expected == actual
        shown = (fingerprint(expected), fingerprint(actual)) if pii else (expected, actual)
        results.append({"task": task, "check": name, "expected": shown[0], "actual": shown[1],
                        "status": "PASS" if ok else "FAIL"})
        echo(f"{'PASS' if ok else 'FAIL'}  {task}  {name}: expected {shown[0]}, got {shown[1]}")

    def one(statement: str):
        return sql(statement)[0][0]

    batches = set(landed.split(","))
    bad = pay["bad_rows"]
    expected_bronze = (pay["baseline_rows"] * ("baseline" in batches) + pay["incident_rows"] * ("incident" in batches)
                       + bad["rows_in_file"] * ("bad_rows" in batches) + pay["drift"]["rows"] * ("drift" in batches))
    check("T03", "bronze.payments rows", expected_bronze, int(one(f"SELECT count(*) FROM {t('bronze', 'payments')}")))

    # Quarantine: every planted bad row, with exactly its rules; drift rows lose amount.
    got = {r[0]: sorted(json.loads(r[1])) for r in sql(
        f"SELECT payment_id, to_json(_failed_rules) FROM {t('quarantine', 'payments')}")}
    expected = {e["payment_id"]: sorted(e["expected_rules"]) for e in bad["quarantine_expected"]}
    check("T03", "planted bad rows quarantined with the right rules",
          len(expected), sum(got.get(k) == v for k, v in expected.items()))
    drift_ids = sql(f"SELECT payment_id FROM {t('bronze', 'payments')} WHERE _source_file LIKE '%payments_drift.json'")
    check("T05", "drift rows quarantined by amount_present",
          pay["drift"]["rows"], sum(got.get(r[0]) == ["amount_present"] for r in drift_ids))
    check("T03", "no unexpected quarantine rows", len(expected) + pay["drift"]["rows"], len(got))

    silver_bad = int(one(f"SELECT count(*) FROM {t('silver', 'payments')} WHERE payment_id IN ({in_list(expected)})"))
    check("T03", "no planted bad row in silver", 0, silver_bad)
    check("T03", "duplicates registered", sorted(bad["duplicate_payment_ids"]),
          sorted(r[0] for r in sql(f"SELECT payment_id FROM {t('quarantine', 'payment_duplicates')}")))
    check("T03", "silver keeps one row per payment_id", 0, int(one(
        f"SELECT count(*) - count(DISTINCT payment_id) FROM {t('silver', 'payments')}")))
    expected_silver = (pay["baseline_rows"] * ("baseline" in batches) + pay["incident_rows"] * ("incident" in batches)
                       + bad["silver_rows_expected"] * ("bad_rows" in batches))
    check("T03", "silver.payments rows", expected_silver, int(one(f"SELECT count(*) FROM {t('silver', 'payments')}")))
    check("T05", "rescued data only on drift rows", pay["drift"]["rows"], int(one(
        f"SELECT count(*) FROM {t('bronze', 'payments')} WHERE _rescued_data IS NOT NULL")))

    # Customers: CDC delete, out-of-order sequencing, SCD2 history, card numbers quarantined, notes redacted.
    cdc = cust["cdc"]
    check("T03", "silver.customers rows (deletes and quarantine applied)", cdc["silver_rows_expected"],
          int(one(f"SELECT count(*) FROM {t('silver', 'customers')}")))
    check("T03", "deleted customer is gone", 0, int(one(
        f"SELECT count(*) FROM {t('silver', 'customers')} WHERE customer_id IN ({in_list(cdc['deleted'])})")))
    ooo = cdc["out_of_order"]
    check("T03", "out-of-order event resolved by seq", ooo["final_address"], one(
        f"SELECT address FROM {t('silver', 'customers')} WHERE customer_id = '{ooo['customer_id']}'"), pii=True)
    history = [r[0] for r in sql(f"SELECT address FROM {t('silver', 'customers_history')} "
                                 f"WHERE customer_id = '{ooo['customer_id']}' ORDER BY __START_AT")]
    check("T03", "SCD2 history keeps sequence order", ooo["history_order"], history[-2:], pii=True)
    check("T04", "card numbers in notes quarantined",
          sorted(x["customer_id"] for x in cust["notes_card_quarantine"]),
          sorted(r[0] for r in sql(f"SELECT customer_id FROM {t('quarantine', 'customers')} "
                                   "WHERE array_contains(_failed_rules, 'notes_no_card_number')")))
    notes = {r[0]: r[1] or "" for r in sql(f"SELECT customer_id, notes_redacted FROM {t('silver', 'customers')}")}
    planted_pii = [p for p in cust["notes_pii"] if p["customer_id"] in notes]
    leaked = sum(p["value"] in notes[p["customer_id"]] for p in planted_pii)
    check("T04", "free-text PII redacted (recall >= 95%)", True, (len(planted_pii) - leaked) / len(planted_pii) >= 0.95)
    check("T04", "new column secondary_email arrived", cust["new_column"]["rows"], int(one(
        f"SELECT count(secondary_email) FROM {t('silver', 'customers')}")))
    return results
