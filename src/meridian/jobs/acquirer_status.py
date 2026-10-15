"""Acquirer status table, rebuilt whenever silver.payments changes (T06 table-update trigger).

An ordinary Delta table, not pipeline-owned, so `RESTORE TABLE` works on it (unlike streaming
tables). Status compares the last 6 hours with the 14-day baseline (failure rate and daily amount);
it holds no SLA terms, which live only in the finance-tier knowledge base.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser


def main() -> None:
    args = parser(__doc__.splitlines()[0]).parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    spark.sql(f"""
        CREATE OR REPLACE TABLE {n.table('gold', 'acquirer_status')}
        COMMENT 'Acquirer health: last 6h vs the 14-day baseline. Rebuilt on each silver.payments update.'
        AS WITH bounds AS (SELECT max(created_at) AS newest FROM {n.table('silver', 'payments')}),
        labelled AS (
          SELECT p.acquirer_id, p.status, p.amount, p.created_at,
                 CASE WHEN p.created_at >= b.newest - INTERVAL 6 HOURS THEN 'recent'
                      WHEN p.created_at >= b.newest - INTERVAL 15 DAYS AND p.created_at < b.newest - INTERVAL 24 HOURS
                      THEN 'baseline' END AS window
          FROM {n.table('silver', 'payments')} p CROSS JOIN bounds b)
        SELECT acquirer_id,
               round(avg(CASE WHEN window = 'recent' THEN IF(status = 'failed', 1.0, 0.0) END), 4) AS recent_failure_rate,
               round(avg(CASE WHEN window = 'baseline' THEN IF(status = 'failed', 1.0, 0.0) END), 4) AS baseline_failure_rate,
               round(sum(CASE WHEN window = 'recent' THEN amount END), 2) AS recent_amount,
               round(sum(CASE WHEN window = 'baseline' THEN amount END)
                     / count(DISTINCT CASE WHEN window = 'baseline' THEN to_date(created_at) END), 2)
                 AS baseline_daily_amount,
               CASE WHEN avg(CASE WHEN window = 'recent' THEN IF(status = 'failed', 1.0, 0.0) END)
                         > 3 * avg(CASE WHEN window = 'baseline' THEN IF(status = 'failed', 1.0, 0.0) END)
                    THEN 'degraded' ELSE 'normal' END AS status,
               current_timestamp() AS updated_at,
               '{args.run_id}' AS run_id
        FROM labelled WHERE window IS NOT NULL GROUP BY acquirer_id
    """)
    for r in spark.sql(f"SELECT acquirer_id, status, recent_failure_rate FROM {n.table('gold', 'acquirer_status')} "
                       "ORDER BY acquirer_id").collect():
        print(r["acquirer_id"], r["status"], r["recent_failure_rate"])


if __name__ == "__main__":
    main()
