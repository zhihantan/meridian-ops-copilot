"""Create or replace the observability views in obs (T06b) from sql/obs_views.sql.

Idempotent. Runs after the pipeline and the quality checks have created the tables the views read.

    obs_views.py --catalog C --bronze-schema S --sql-file .../sql/obs_views.sql --target prod --workspace-id W
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession

from meridian.common.sqlfile import statements
from meridian.jobs.common import names, parser


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--sql-file", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--workspace-id", required=True)
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    values = {"catalog": n.catalog, "target": args.target, "workspace_id": args.workspace_id,
              **{layer: f"{n.catalog}.{n.schema(layer)}" for layer in ("obs", "gov", "quarantine")}}
    for statement in statements(args.sql_file, values):
        spark.sql(statement)
        print("ok:", statement.split("\n", 1)[0])


if __name__ == "__main__":
    main()
