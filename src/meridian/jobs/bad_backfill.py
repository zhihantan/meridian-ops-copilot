"""Demo fault (T06): a "backfill" that corrupts one day of silver.payments by applying a x100
currency conversion twice. Lineage then answers "which jobs touched silver.payments?" with this job's
run ID. Recovery: refresh silver.payments from bronze (a streaming table cannot be RESTOREd), then
RESTORE the ordinary gold.acquirer_status table or let the table-update trigger rebuild it.
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
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--days-ago", type=int, default=3, help="which Singapore-time day to corrupt")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    silver = n.table("silver", "payments")
    day = f"date_sub(to_date(from_utc_timestamp(current_timestamp(), 'Asia/Singapore')), {args.days_ago})"
    result = spark.sql(f"UPDATE {silver} SET amount = amount * 100 "
                       f"WHERE to_date(from_utc_timestamp(created_at, 'Asia/Singapore')) = {day}")
    print(f"corrupted rows: {result.first()}")


if __name__ == "__main__":
    main()
