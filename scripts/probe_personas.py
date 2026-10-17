"""Run the same queries as each persona and record what they see (T04 evidence; reused by T19).

Ava (support) should get masked contacts, no NRIC or card, and home-market payments only. Ben
(finance) sees every market but still masked PII. Eli (admin, the presenter) sees everything.

    uv run --group dbx python scripts/probe_personas.py --target dev
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql, warehouse_id

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "T04"
PERSONAS = {"ava": "meridian-ava", "ben": "meridian-ben", "eli": None}  # None: the presenter's own profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="dev")
    args = parser.parse_args()
    names = target_names(args.target)
    customers, payments = names.table("silver", "customers"), names.table("silver", "payments")
    queries = {
        "customer_pii": f"SELECT customer_id, full_name, email, phone, national_id, card_number, dob "
                        f"FROM {customers} WHERE customer_id = 'c_00003'",
        "payments_by_country": f"SELECT country, count(*) AS n FROM {payments} GROUP BY 1 ORDER BY 1",
        "notes_redacted_sample": f"SELECT notes_redacted FROM {customers} WHERE contains_pii LIMIT 1",
    }
    wh = warehouse_id(WorkspaceClient())
    results = {}
    for persona, profile in PERSONAS.items():
        w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
        results[persona] = {}
        for name, statement in queries.items():
            try:
                results[persona][name] = sql(w, statement, warehouse=wh)
            except Exception as exc:  # noqa: BLE001  a denial is a valid, recorded outcome
                results[persona][name] = f"denied: {str(exc).splitlines()[0][:160]}"
            print(f"{persona:4} {name}: {results[persona][name]}")

    ava, eli = results["ava"]["customer_pii"], results["eli"]["customer_pii"]
    checks = {
        "ava_email_masked": isinstance(ava, list) and "***@" in (ava[0][2] or ""),
        "ava_nric_hidden": isinstance(ava, list) and ava[0][4] is None,
        "eli_sees_raw_email": isinstance(eli, list) and "***" not in (eli[0][2] or ""),
        "ava_home_market_only": isinstance(results["ava"]["payments_by_country"], list)
                                and {r[0] for r in results["ava"]["payments_by_country"]} == {"SG"},
        "ben_all_markets": isinstance(results["ben"]["payments_by_country"], list)
                           and len(results["ben"]["payments_by_country"]) > 1,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    # Keep unmasked values (synthetic, but PII-shaped) out of the committed evidence: record only that they were
    # visible. Masked values ("***") and hidden ones (NULL) are kept as returned.
    for seen in results.values():
        if isinstance(seen.get("customer_pii"), list):
            seen["customer_pii"] = [[c if i == 0 or c is None or "***" in str(c) else f"<unmasked, {len(str(c))} chars>"
                                     for i, c in enumerate(row)] for row in seen["customer_pii"]]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"persona_probe_{args.target}.json").write_text(json.dumps(
        {"target": args.target, "ran_at": datetime.now(UTC).isoformat(), "results": results,
         "checks": checks, "status": status}, indent=2, default=str))
    print(checks, status)


if __name__ == "__main__":
    main()
