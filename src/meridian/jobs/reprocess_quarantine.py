"""Reprocess quarantined payments through the current contract rules (T03, BUILD).

Selects unreprocessed rows (optionally one rule and a time window), re-evaluates them with the rules
as they are now, MERGEs the rows that pass into silver.payments (idempotent on payment_id), stamps
reprocessed_at on them and writes an audit row. A second run changes nothing.

    reprocess_quarantine.py --catalog C --bronze-schema S [--rule currency_valid] [--since-hours 48]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession

from meridian.contracts.compiler import load_all
from meridian.jobs.common import names, parser


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--rule", default="", help="only rows that failed this rule (empty for all)")
    p.add_argument("--since-hours", type=int, default=0, help="only rows quarantined in this window (0 for all)")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    contract = load_all()["payments"]
    quarantine, silver = n.table("quarantine", "payments"), n.table("silver", "payments")

    where = ["reprocessed_at IS NULL"]
    if args.rule:
        where.append(f"array_contains(_failed_rules, '{args.rule}')")
    if args.since_hours:
        where.append(f"_quarantined_at >= current_timestamp() - INTERVAL {args.since_hours} HOURS")
    candidates = spark.sql(f"SELECT * FROM {quarantine} WHERE {' AND '.join(where)}") \
        .selectExpr("*", f"{contract.failed_rules_sql()} AS _still_failing")
    candidates.createOrReplaceTempView("candidates")
    considered = candidates.count()
    released = spark.sql("SELECT * FROM candidates WHERE size(_still_failing) = 0")
    released.createOrReplaceTempView("released")
    released_ids = [r["payment_id"] for r in released.select("payment_id").collect()]

    if released_ids:
        columns = [f.name for f in spark.read.table(silver).schema.fields]
        col_list = ", ".join(columns)
        spark.sql(f"""
            MERGE INTO {silver} AS s
            USING (SELECT {col_list} FROM released) AS r ON s.payment_id = r.payment_id
            WHEN NOT MATCHED THEN INSERT ({col_list}) VALUES ({', '.join('r.' + c for c in columns)})
        """)
        id_list = ", ".join(f"'{i}'" for i in released_ids)
        spark.sql(f"UPDATE {quarantine} SET reprocessed_at = current_timestamp() WHERE payment_id IN ({id_list})")

    audit = n.table("obs", "reprocess_audit")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {audit} (run_id STRING, ran_at TIMESTAMP, rule STRING, "
              "since_hours INT, rows_considered BIGINT, rows_released BIGINT, released_ids ARRAY<STRING>)")
    spark.createDataFrame(
        [(args.run_id, args.rule or None, args.since_hours, considered, len(released_ids), released_ids)],
        "run_id STRING, rule STRING, since_hours INT, rows_considered BIGINT, rows_released BIGINT, released_ids ARRAY<STRING>",
    ).selectExpr("run_id", "current_timestamp() AS ran_at", "rule", "since_hours", "rows_considered",
                 "rows_released", "released_ids").write.mode("append").saveAsTable(audit)
    print(f"considered {considered}, released {len(released_ids)} into {silver}")


if __name__ == "__main__":
    main()
