"""Generic file ingestion for config-generated jobs (T06c): Auto Loader, available-now, into bronze.<source>.

One script serves every generated job; each job differs only by its parameters.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from meridian.jobs.common import names, parser


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--source", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--format", default="json")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    try:
        files = spark.sql(f"LIST '{args.path}'").count()
    except Exception:  # noqa: BLE001  the landing folder does not exist yet
        files = 0
    if not files:
        print(f"{args.source}: no files at {args.path}; nothing to ingest")
        return
    checkpoint = f"{args.path.rsplit('/', 1)[0]}/_checkpoints/{args.source}"
    query = (spark.readStream.format("cloudFiles")
             .option("cloudFiles.format", args.format)
             .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
             .option("header", "true")
             .load(args.path)
             .select("*", F.col("_metadata.file_path").alias("_source_file"), F.current_timestamp().alias("_ingested_at"))
             .writeStream.option("checkpointLocation", checkpoint).trigger(availableNow=True)
             .toTable(n.table("bronze", args.source)))
    query.awaitTermination()
    print(f"{args.source}: ingested into {n.table('bronze', args.source)}")


if __name__ == "__main__":
    main()
