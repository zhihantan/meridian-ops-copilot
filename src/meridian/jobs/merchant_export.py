"""Finance merchant export (T06b): yesterday's merchant totals from gold.merchant_daily as a CSV file.

A new consumer of a gold table. Deployed after the first lineage snapshot, its read shows up as an
"added" edge in gov.lineage_changelog.

    merchant_export.py --catalog C --bronze-schema S
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import csv

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser


def main() -> None:
    args = parser(__doc__.splitlines()[0]).parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    rows = spark.sql(f"""
        SELECT payment_date, merchant_id, currency, payments, failed_payments, round(gross_amount, 2) AS gross_amount
        FROM {n.table('gold', 'merchant_daily')}
        WHERE payment_date = date_sub(to_date(from_utc_timestamp(current_timestamp(), 'Asia/Singapore')), 1)
        ORDER BY merchant_id, currency""").collect()
    folder = Path(f"/Volumes/{n.catalog}/{n.schema('obs')}/exports/merchant_daily")
    folder.mkdir(parents=True, exist_ok=True)
    day = rows[0]["payment_date"].isoformat() if rows else "none"
    with (folder / f"merchant_daily_{day}.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["payment_date", "merchant_id", "currency", "payments", "failed_payments", "gross_amount"])
        writer.writerows([list(r) for r in rows])
    print(f"{len(rows)} merchant rows for {day} -> {folder}")


if __name__ == "__main__":
    main()
