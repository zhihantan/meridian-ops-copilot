"""Release log (T09): one obs.releases row per deployment or rollback, run after deploying from the bundle UI.

    release_log.py --catalog C --bronze-schema S --kind deploy|rollback --ref v1.2.0 --sha <git sha> --actor <user> --run-url <url>
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
    for flag in ("--kind", "--ref", "--sha", "--actor", "--run-url"):
        p.add_argument(flag, default="")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    table = n.table("obs", "releases")
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {table}
                  (released_at TIMESTAMP, kind STRING, ref STRING, sha STRING, actor STRING, ci_run_url STRING,
                   job_run_id STRING) COMMENT 'Deployments and rollbacks, one row per release (T09)'""")
    row = [(args.kind, args.ref, args.sha, args.actor, args.run_url, args.run_id)]
    (spark.createDataFrame(row, "kind STRING, ref STRING, sha STRING, actor STRING, ci_run_url STRING, job_run_id STRING")
     .selectExpr("current_timestamp() AS released_at", "*").write.mode("append").saveAsTable(table))
    print(f"logged {args.kind} {args.ref} ({args.sha[:12]}) to {table}")


if __name__ == "__main__":
    main()
