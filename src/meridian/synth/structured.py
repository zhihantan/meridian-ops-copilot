"""Seeded synthetic payments and customers for the Meridian POC (T02).

Writes landing batches as NDJSON plus planted.json, the ground truth every check scores against.
IDs and values depend only on the seed; timestamps are relative to --anchor, so the "last 24h"
windows stay correct whenever the data is regenerated.

    uv run python -m meridian.synth.structured --anchor now --out data/out
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = REPO_ROOT / "config" / "scenario.yaml"
EVIDENCE_PATH = REPO_ROOT / "docs" / "evidence" / "T02" / "planted_summary.json"

# Well-known test card numbers; never real cards.
TEST_CARDS = ["4111111111111111", "5555555555554444", "4242424242424242", "4000056655665556"]
FIRST_NAMES = [
    "Wei Ling", "Jun Jie", "Siti", "Arjun", "Mei Xin", "Hafiz", "Priya", "Daniel", "Nur Aisyah",
    "Kai Wen", "Rajesh", "Charlotte", "Farah", "Marcus", "Hui Min", "Vikram", "Aminah", "Ethan",
]
LAST_NAMES = [
    "Tan", "Lim", "Lee", "Ng", "Wong", "Goh", "Chua", "Koh", "Teo", "Rahman", "Abdullah",
    "Kumar", "Nair", "Pillai", "Fernandez", "Ong", "Chong", "Yeo",
]
STREETS = ["Ang Mo Kio Ave 3", "Tampines St 81", "Jurong West St 52", "Bedok North Rd", "Toa Payoh Lor 1",
           "Clementi Ave 2", "Yishun Ring Rd", "Punggol Field", "Bukit Batok St 21", "Sengkang East Way"]
BENIGN_NOTES = [
    "Prefers PayNow for refunds.", "Asked about delivery times for marketplace orders.",
    "Long-time customer, usually pays by card.", "Requested invoice copies for last quarter.",
    "Reported a slow checkout page, resolved after app update.", "Opted out of marketing emails.",
]
CURRENCY_COUNTRY = {"SGD": "SG", "MYR": "MY", "IDR": "ID", "THB": "TH", "PHP": "PH", "USD": "SG", "VND": "VN"}


def load_scenario(path: Path = SCENARIO_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def parse_anchor(value: str) -> datetime:
    """Anchor floored to the hour, in UTC. 'now' or an ISO timestamp."""
    if value == "now":
        anchor = datetime.now(UTC)
    else:
        anchor = datetime.fromisoformat(value)
        anchor = anchor.replace(tzinfo=anchor.tzinfo or UTC).astimezone(UTC)
    return anchor.replace(minute=0, second=0, microsecond=0)


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def hex_id(rng: random.Random, prefix: str, n: int = 16) -> str:
    return f"{prefix}{rng.getrandbits(4 * n):0{n}x}"


def nric(rng: random.Random) -> str:
    """Singapore NRIC-format value with a valid check letter. Random; not linked to any person."""
    prefix = rng.choice("ST")
    digits = [rng.randint(0, 9) for _ in range(7)]
    total = sum(d * w for d, w in zip(digits, [2, 7, 6, 5, 4, 3, 2])) + (4 if prefix == "T" else 0)
    return prefix + "".join(map(str, digits)) + "JZIHGFEDCBA"[total % 11]


def sg_phone(rng: random.Random, with_country_code: bool = True) -> str:
    number = f"{rng.choice('89')}{rng.randint(0, 999):03d} {rng.randint(0, 9999):04d}"
    return f"+65 {number}" if with_country_code else number


# ---------------------------------------------------------------- payments


class PaymentFactory:
    def __init__(self, rng: random.Random, scenario: dict):
        self.rng = rng
        self.p = scenario["payments"]
        self.acquirers = scenario["acquirers"]
        self.n_customers = scenario["customers"]["rows"]

    def row(self, ts: datetime, incident: bool) -> dict:
        rng, p = self.rng, self.p
        acq = rng.choice(self.acquirers)
        rate = acq.get("incident_failure_rate", acq["failure_rate"]) if incident else acq["failure_rate"]
        weights = p["failure_code_weights"]["incident" if incident and "incident_failure_rate" in acq
                                            else "baseline"]
        failed = rng.random() < rate
        if "currencies" in acq:  # a domestic acquirer, e.g. acq_7 is SGD only
            currency = rng.choice(acq["currencies"])
        else:
            currency = rng.choices(p["currencies"]["allowed"], p["currencies"]["weights"])[0]
        null_rate = p["device_id_null_rate"]["incident" if incident else "baseline"]
        device_id = None if rng.random() < null_rate else hex_id(rng, "dev_", 8)
        return {
            "payment_id": hex_id(rng, "pay_"),
            "merchant_id": f"m_{rng.randint(1, p['merchants']):04d}",
            "customer_id": f"c_{rng.randint(1, self.n_customers):05d}",
            "acquirer_id": acq["id"],
            "amount": round(min(rng.lognormvariate(3.6, 0.9), 4999.0), 2),
            "currency": currency,
            "payment_method": rng.choice(p["payment_methods"]),
            "status": "failed" if failed else "succeeded",
            "failure_code": rng.choices(p["failure_codes"], weights)[0] if failed else None,
            "device_id": device_id,
            "country": CURRENCY_COUNTRY[currency],
            "created_at": iso(ts),
        }

    def at_random(self, start: datetime, span: timedelta, incident: bool) -> dict:
        return self.row(start + timedelta(seconds=self.rng.uniform(0, span.total_seconds())), incident)


def gen_payments(rng: random.Random, scenario: dict, anchor: datetime) -> tuple[dict, dict]:
    p = scenario["payments"]
    f = PaymentFactory(rng, scenario)
    sgt = ZoneInfo(scenario["display_timezone"])
    batches: dict[str, dict[str, list[dict]]] = {}

    incident_start = anchor - timedelta(hours=24)
    incident_end = incident_start + timedelta(hours=p["incident_hours"])
    baseline_start = incident_start - timedelta(days=p["baseline_days"])

    def name(ts: datetime) -> str:
        return f"payments_{ts.astimezone(sgt):%Y%m%dT%H}.json"

    # Clean history, one file per 24h block: the drift baseline.
    batches["baseline"] = {}
    for d in range(p["baseline_days"]):
        start = baseline_start + timedelta(days=d)
        rows = sorted((f.at_random(start, timedelta(days=1), False) for _ in range(p["baseline_rows_per_day"])),
                      key=lambda r: r["created_at"])
        batches["baseline"][name(start)] = rows

    # Last 24h minus the arrival gap, hourly files: acq_7 failure spike and device_id null spike.
    batches["incident"] = {}
    for h in range(p["incident_hours"]):
        start = incident_start + timedelta(hours=h)
        rows = sorted((f.at_random(start, timedelta(hours=1), True) for _ in range(p["incident_rows_per_hour"])),
                      key=lambda r: r["created_at"])
        batches["incident"][name(start)] = rows

    span = incident_end - incident_start

    def clean() -> dict:
        return f.at_random(incident_start, span, False)

    # Bad-rows file: one defect per row (plus two double defects), duplicates of clean rows.
    bad_rows, expected = [], []
    clean_rows = [clean() for _ in range(20)]
    defects = (
        [("merchant_id_not_null",)] * 12 + [("amount_positive",)] * 9 + [("currency_valid", "SGX")] * 7
        + [("currency_valid", "VND")] * 5 + [("merchant_id_not_null", "amount_positive")] * 2
    )
    for defect in defects:
        row = clean()
        rules = []
        if "merchant_id_not_null" in defect:
            row["merchant_id"] = None
            rules.append("merchant_id_not_null")
        if "amount_positive" in defect:
            row["amount"] = -row["amount"]
            rules.append("amount_positive")
        if defect[0] == "currency_valid":
            row["currency"], row["country"] = defect[1], CURRENCY_COUNTRY.get(defect[1], "SG")
            rules.append("currency_valid")
        bad_rows.append(row)
        expected.append({"payment_id": row["payment_id"], "expected_rules": rules,
                         "relaxable": defect[0] == "currency_valid" and defect[1] == "VND"})
    duplicates = [dict(r) for r in rng.sample(clean_rows, 6)]
    bad_file_rows = clean_rows + bad_rows + duplicates
    rng.shuffle(bad_file_rows)
    batches["bad_rows"] = {"payments_bad_rows.json": bad_file_rows}

    # Critical file: one null payment_id fails the update.
    critical_rows = [clean() for _ in range(10)]
    critical_bad = clean()
    critical_bad["payment_id"] = None
    critical_rows.insert(rng.randint(0, 10), critical_bad)
    batches["critical"] = {"payments_critical.json": critical_rows}

    # Schema drift: a new column, and amount as a string with a unit. Spark's JSON reader coerces plain
    # numeric strings such as "49.90" into DECIMAL, so the planted value must be unparseable.
    drift_rows = []
    for _ in range(50):
        row = clean()
        row["amount"] = f"{abs(row['amount']):.2f} {row['currency']}"
        row["payment_method_v2"] = f"{row['payment_method']}:{rng.choice(['visa', 'mastercard', 'local'])}"
        drift_rows.append(row)
    batches["drift"] = {"payments_drift.json": drift_rows}

    planted = {
        "windows": {
            "baseline_start": iso(baseline_start), "incident_start": iso(incident_start),
            "incident_end": iso(incident_end), "anchor": iso(anchor),
        },
        "baseline_rows": sum(len(r) for r in batches["baseline"].values()),
        "incident_rows": sum(len(r) for r in batches["incident"].values()),
        "bad_rows": {
            "file": "payments_bad_rows.json",
            "rows_in_file": len(bad_file_rows),
            "clean_rows": len(clean_rows),
            "quarantine_expected": expected,
            "counts_by_rule": _count_rules(expected),
            "relaxable_currency": p["currencies"]["relaxable"],
            "relaxable_rows": sum(e["relaxable"] for e in expected),
            "duplicate_payment_ids": sorted(r["payment_id"] for r in duplicates),
            "silver_rows_expected": len(clean_rows),
        },
        "critical": {"file": "payments_critical.json", "rule": "payment_id_not_null", "violations": 1,
                     "expected": "update fails and pages"},
        "drift": {
            "file": "payments_drift.json", "rows": len(drift_rows), "new_columns": ["payment_method_v2"],
            "type_changes": {"amount": "string with currency suffix, e.g. '49.90 SGD'"},
            "expected": "all rows have non-null _rescued_data; amount_present quarantines them",
        },
        "freshness_gap": {
            "last_event_before": iso(incident_end), "gap_hours": p["arrival_gap_hours"],
            "max_delay_minutes": p["max_delay_minutes"],
        },
        "incident_stats": _incident_stats(batches, scenario),
    }
    return batches, planted


def _count_rules(expected: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for e in expected:
        for rule in e["expected_rules"]:
            counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items()))


def _incident_stats(batches: dict, scenario: dict) -> dict:
    refundable = set(scenario["policy"]["refundable_failure_codes"])
    sla_acq = scenario["policy"]["sla"]["acquirer"]

    def rates(rows: list[dict]) -> dict:
        out = {}
        for acq in sorted({r["acquirer_id"] for r in rows}):
            sub = [r for r in rows if r["acquirer_id"] == acq]
            out[acq] = round(sum(r["status"] == "failed" for r in sub) / len(sub), 4)
        return out

    base = [r for rows in batches["baseline"].values() for r in rows]
    inc = [r for rows in batches["incident"].values() for r in rows]
    refund_rows = [r for r in inc if r["acquirer_id"] == sla_acq and r["status"] == "failed"
                   and r["failure_code"] in refundable]
    return {
        "failure_rate_baseline": rates(base),
        "failure_rate_incident": rates(inc),
        "device_id_null_rate": {
            "baseline": round(sum(r["device_id"] is None for r in base) / len(base), 4),
            "incident": round(sum(r["device_id"] is None for r in inc) / len(inc), 4),
        },
        "refund_candidates": {
            "acquirer": sla_acq, "failure_codes": sorted(refundable), "count": len(refund_rows),
            "total_amount_by_currency": _sum_by(refund_rows, "currency"),
            "payment_ids": sorted(r["payment_id"] for r in refund_rows),
        },
    }


def _sum_by(rows: list[dict], key: str) -> dict:
    out: dict[str, float] = {}
    for r in rows:
        out[r[key]] = round(out.get(r[key], 0.0) + r["amount"], 2)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- customers


def gen_customers(rng: random.Random, scenario: dict, anchor: datetime) -> tuple[dict, dict]:
    c = scenario["customers"]
    domain = c["email_domain"]
    n = c["rows"]
    seq = 0

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    def person(i: int) -> dict:
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        handle = f"{first.lower().replace(' ', '')}.{last.lower()}{i}"
        born = anchor.date() - timedelta(days=rng.randint(18 * 365, 70 * 365))
        return {
            "customer_id": f"c_{i:05d}",
            "full_name": f"{first} {last}",
            "email": f"{handle}@{domain}",
            "phone": sg_phone(rng),
            "national_id": nric(rng),
            "dob": born.isoformat(),
            "address": f"Blk {rng.randint(1, 999)} {rng.choice(STREETS)} #{rng.randint(2, 25):02d}-"
                       f"{rng.randint(1, 400):03d}, Singapore {rng.randint(100000, 829999)}",
            "card_number": rng.choice(TEST_CARDS),
            "notes": rng.choice(BENIGN_NOTES + [None, None]),
            "created_at": iso(anchor - timedelta(days=rng.randint(30, 1000))),
        }

    snapshot_ts = anchor - timedelta(days=20)
    people = [person(i) for i in range(1, n + 1)]

    # Free-text PII typed by support agents, plus card numbers that must be quarantined.
    notes_pii, notes_card = [], []
    reserved = {41, 76}  # c_00042 (delete) and c_00077 (out-of-order) keep plain notes
    ids = rng.sample([i for i in range(n) if i not in reserved], c["notes_with_pii"] + c["notes_with_card"])
    for k, idx in enumerate(ids[: c["notes_with_pii"]]):
        kind = ("email", "phone", "national_id")[k % 3]
        if kind == "email":
            value = f"alt.{rng.getrandbits(24):06x}@{domain}"
            text = f"Asked us to send the receipt to {value} instead."
        elif kind == "phone":
            value = sg_phone(rng, with_country_code=k % 2 == 0)
            text = f"Call back on {value} after 6pm."
        else:
            value = nric(rng)
            text = f"Verified identity with NRIC {value} over the phone."
        people[idx]["notes"] = text
        notes_pii.append({"customer_id": people[idx]["customer_id"], "type": kind, "value": value})
    for idx in ids[c["notes_with_pii"]:]:
        card = rng.choice(TEST_CARDS)
        spaced = " ".join(card[i:i + 4] for i in range(0, len(card), 4))
        people[idx]["notes"] = f"Customer read out card {spaced} in chat; advised not to share card details."
        notes_card.append({"customer_id": people[idx]["customer_id"], "value": spaced})

    initial = []
    for i, row in enumerate(people):
        initial.append({**row, "op": "I", "seq": next_seq(), "op_ts": iso(snapshot_ts + timedelta(seconds=i))})

    special = {"c_00042", "c_00077"} | {x["customer_id"] for x in notes_card}
    pool = [r for r in people if r["customer_id"] not in special]
    changes_1_ts, changes_2_ts = anchor - timedelta(days=2), anchor - timedelta(days=1)

    def update(row: dict, ts: datetime, **fields) -> dict:
        new = {**row, **fields}
        row.update(fields)
        return {**new, "op": "U", "seq": next_seq(), "op_ts": iso(ts)}

    changes_1, updates = [], []
    for k, row in enumerate(rng.sample(pool, 60)):
        field = ("phone", "address", "email")[k % 3]
        value = {"phone": sg_phone(rng), "email": f"new.{rng.getrandbits(24):06x}@{domain}",
                 "address": f"Blk {rng.randint(1, 999)} {rng.choice(STREETS)}, Singapore {rng.randint(100000, 829999)}"}[field]
        changes_1.append(update(row, changes_1_ts + timedelta(minutes=k), **{field: value}))
        updates.append({"customer_id": row["customer_id"], "field": field})

    by_id = {r["customer_id"]: r for r in people}
    deleted = by_id["c_00042"]
    changes_1.append({"customer_id": deleted["customer_id"], "op": "D", "seq": next_seq(),
                      "op_ts": iso(changes_1_ts + timedelta(hours=1))})

    # Out of order: the newer event (B) lands first; the older one (A) arrives a file later.
    c77 = by_id["c_00077"]
    seq_a, seq_b = next_seq(), next_seq()
    addr_a = "Blk 11 Holland Dr #05-120, Singapore 271011"
    addr_b = "Blk 210 Bishan St 23 #09-301, Singapore 570210"
    changes_1.append({**c77, "address": addr_b, "op": "U", "seq": seq_b, "op_ts": iso(changes_1_ts + timedelta(hours=2))})
    changes_2 = [{**c77, "address": addr_a, "op": "U", "seq": seq_a, "op_ts": iso(changes_1_ts + timedelta(hours=1))}]
    c77["address"] = addr_b

    # New unprotected PII column arrives in a later file (T04 pii_coverage, T05 schema evolution).
    secondary = []
    for k, row in enumerate(rng.sample([r for r in pool if r["customer_id"] not in {u["customer_id"] for u in updates}], 25)):
        value = f"{row['customer_id'].replace('_', '')}.backup@{domain}"
        changes_2.append({**update(row, changes_2_ts + timedelta(minutes=k)), "secondary_email": value})
        secondary.append(row["customer_id"])

    batches = {
        "initial": {"customers_initial.json": initial},
        "changes_1": {"customers_changes_1.json": changes_1},
        "changes_2": {"customers_changes_2.json": changes_2},
    }
    planted = {
        "rows": n,
        "pii_columns": {"email": "email", "phone": "phone", "national_id": "national_id (SG NRIC format)",
                        "card_number": "card (test PANs)", "dob": "dob", "full_name": "name", "address": "address"},
        "notes_pii": notes_pii,
        "notes_card_quarantine": notes_card,
        "cdc": {
            "updates_file_1": len(updates), "deleted": ["c_00042"],
            "out_of_order": {"customer_id": "c_00077", "late_seq": seq_a, "winning_seq": seq_b,
                             "final_address": addr_b, "history_order": [addr_a, addr_b]},
            "silver_rows_expected": n - 1 - len(notes_card),
        },
        "new_column": {"name": "secondary_email", "file": "customers_changes_2.json", "rows": len(secondary),
                       "expected": "pii_coverage alerts: PII-like column with no protection"},
    }
    return batches, planted


# ---------------------------------------------------------------- output


def write_batches(out: Path, dataset: str, batches: dict) -> None:
    for batch, files in batches.items():
        folder = out / dataset / batch
        folder.mkdir(parents=True, exist_ok=True)
        for filename, rows in files.items():
            with open(folder / filename, "w") as fh:
                fh.writelines(json.dumps(row) + "\n" for row in rows)


def generate(anchor: datetime, out: Path, scenario: dict | None = None) -> dict:
    scenario = scenario or load_scenario()
    rng = random.Random(scenario["seed"])
    payments, planted_payments = gen_payments(rng, scenario, anchor)
    customers, planted_customers = gen_customers(rng, scenario, anchor)
    if out.exists():
        for sub in ("payments", "customers_changes"):
            shutil.rmtree(out / sub, ignore_errors=True)
    write_batches(out, "payments", payments)
    write_batches(out, "customers_changes", customers)
    planted = {"seed": scenario["seed"], "anchor": iso(anchor), "payments": planted_payments,
               "customers": planted_customers}
    (out / "planted.json").write_text(json.dumps(planted, indent=2))
    return planted


def public_summary(planted: dict) -> dict:
    """planted.json without raw PII values (NRIC-format strings, phone numbers), safe for a public repo."""
    summary = json.loads(json.dumps(planted))
    cust = summary["customers"]
    cust["notes_pii"] = {k: sum(p["type"] == k for p in planted["customers"]["notes_pii"])
                         for k in ("email", "phone", "national_id")}
    cust["notes_card_quarantine"] = [x["customer_id"] for x in planted["customers"]["notes_card_quarantine"]]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--anchor", default="now", help="'now' or an ISO timestamp")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "out")
    parser.add_argument("--evidence", action="store_true", help="also copy planted.json to docs/evidence/T02/")
    args = parser.parse_args()
    planted = generate(parse_anchor(args.anchor), args.out)
    if args.evidence:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(json.dumps(public_summary(planted), indent=2))
    pay = planted["payments"]
    stats = pay["incident_stats"]
    print(f"anchor {planted['anchor']}: baseline {pay['baseline_rows']} rows, incident {pay['incident_rows']} rows")
    print(f"acq_7 failure rate {stats['failure_rate_baseline']['acq_7']} -> {stats['failure_rate_incident']['acq_7']}; "
          f"device_id null {stats['device_id_null_rate']['baseline']} -> {stats['device_id_null_rate']['incident']}")
    print(f"bad rows {pay['bad_rows']['counts_by_rule']}, duplicates {len(pay['bad_rows']['duplicate_payment_ids'])}; "
          f"refund candidates {stats['refund_candidates']['count']} {stats['refund_candidates']['total_amount_by_currency']}")


if __name__ == "__main__":
    main()
