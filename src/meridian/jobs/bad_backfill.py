"""Demo fault (T06): an "FX correction" backfill that corrupts one day of silver.payments.

It loads correction factors into bronze.fx_corrections with a units bug (100 instead of 1, cents
for dollars) and MERGEs the corrected amounts into silver.payments. DESCRIBE HISTORY on silver.payments
names the job and run immediately. Lineage records the job reading silver.payments and writing
bronze.fx_corrections, but not its MERGE into the streaming table: DML into a pipeline table from a
job is not a lineage write edge (observed 2026-10-15).

Recovery: RESTORE the ordinary gold.acquirer_status table, then a selective full refresh of
silver.payments from bronze (a streaming table cannot be RESTOREd). See docs/runbooks/bad_backfill.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser

SGT_DAY = "to_date(from_utc_timestamp(created_at, 'Asia/Singapore'))"


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--days-ago", type=int, default=3, help="which Singapore-time day to corrupt")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    silver, corrections = n.table("silver", "payments"), n.table("bronze", "fx_corrections")
    day = f"date_sub(to_date(from_utc_timestamp(current_timestamp(), 'Asia/Singapore')), {args.days_ago})"
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {corrections}
                  (correction_date DATE, currency STRING, factor DECIMAL(12, 4), reason STRING,
                   loaded_at TIMESTAMP, run_id STRING)
                  COMMENT 'FX correction factors loaded by the backfill job (demo fault: factor 100 is a units bug).'""")
    spark.sql(f"""INSERT INTO {corrections}
                  SELECT DISTINCT {day}, currency, 100, 'FX restatement', current_timestamp(), '{args.run_id}'
                  FROM {silver} WHERE {SGT_DAY} = {day}""")
    result = spark.sql(f"""
        MERGE INTO {silver} t
        USING (SELECT p.payment_id, p.amount * c.factor AS amount
               FROM {silver} p JOIN {corrections} c
                 ON {SGT_DAY.replace('created_at', 'p.created_at')} = c.correction_date AND p.currency = c.currency
               WHERE c.run_id = '{args.run_id}') s
        ON t.payment_id = s.payment_id
        WHEN MATCHED THEN UPDATE SET t.amount = s.amount""")
    print(f"corrected rows: {result.first()}")


if __name__ == "__main__":
    main()
