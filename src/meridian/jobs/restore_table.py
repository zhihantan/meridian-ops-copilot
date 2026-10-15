"""Runbook job (T06): RESTORE an ordinary Delta table of this target to an earlier version.

Native RESTORE, wrapped in a job so that prod recovery runs as the deploying service principal from a
reviewed bundle, with the request in the job run's parameters; no person needs standing MODIFY on
prod. Refuses pipeline streaming tables and materialized views, which RESTORE does not support
(recover those with a selective full refresh). Writes an obs.recovery_audit row.

    restore_table.py --catalog C --bronze-schema S --table gold.acquirer_status --version 0
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
    p.add_argument("--table", required=True, help="<layer>.<name>, for example gold.acquirer_status")
    p.add_argument("--version", type=int, required=True)
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    layer, name = args.table.split(".")
    table = n.table(layer, name)
    kind = {r["col_name"]: r["data_type"] for r in spark.sql(f"DESCRIBE TABLE EXTENDED {table}").collect()}.get("Type")
    if kind != "MANAGED":
        raise SystemExit(f"{table} is {kind}; RESTORE is for ordinary Delta tables. Use a pipeline full refresh.")
    current = spark.sql(f"DESCRIBE HISTORY {table} LIMIT 1").first()["version"]
    print(spark.sql(f"RESTORE TABLE {table} TO VERSION AS OF {args.version}").first())
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {n.table('obs', 'recovery_audit')}
                  (restored_at TIMESTAMP, table_name STRING, from_version BIGINT, to_version BIGINT, run_id STRING)""")
    spark.sql(f"""INSERT INTO {n.table('obs', 'recovery_audit')}
                  VALUES (current_timestamp(), '{table}', {current}, {args.version}, '{args.run_id}')""")
    print(f"restored {table} from version {current} to {args.version}")


if __name__ == "__main__":
    main()
