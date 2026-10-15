"""Lineage changelog (T06b, BUILD over automatic lineage): snapshot this target's edges, record changes.

Each run takes the distinct edges of the last 7 days from system.access.table_lineage (source, target,
entity type and ID, where source or target is in this target's catalog and schemas) into
gov.lineage_snapshot, compares the edges that touch a data layer with the previous snapshot, and appends
the differences to gov.lineage_changelog: "added", or "not_seen_7d" for an edge with no event in the window, with who
created the edge and when it was first and last seen. The first run records a baseline. Lineage lags,
so a new edge shows up on the first run after its event reaches the system table.

    lineage_changelog.py --catalog C --bronze-schema S
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from meridian.jobs.common import names, parser

EDGE = ["source", "target", "entity_type", "entity_id"]
# The changelog reports edges that touch a data layer; edges among obs, gov and system tables are the
# observability jobs themselves. The snapshot keeps every edge.
DATA_LAYERS = ("landing", "bronze", "silver", "quarantine", "gold", "kb", "agent", "eval")


def main() -> None:
    args = parser(__doc__.splitlines()[0]).parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    snapshot_t, changelog_t = n.table("gov", "lineage_snapshot"), n.table("gov", "lineage_changelog")
    snapshot_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{args.run_id}"
    in_scope = (f"(source_table_catalog = '{n.catalog}' AND startswith(source_table_schema, '{n.prefix}')) OR "
                f"(target_table_catalog = '{n.catalog}' AND startswith(target_table_schema, '{n.prefix}'))")
    current = spark.sql(f"""
        WITH jobs AS (SELECT job_id, name FROM system.lakeflow.jobs
                      QUALIFY row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) = 1),
             pipes AS (SELECT pipeline_id, name FROM system.lakeflow.pipelines
                       QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1),
             edges AS (
               SELECT coalesce(source_table_full_name, source_path, '') AS source,
                      coalesce(target_table_full_name, target_path, '') AS target,
                      entity_type, entity_id,
                      max_by(created_by, event_time) AS created_by,
                      min(event_time) AS first_seen, max(event_time) AS last_seen, count(*) AS events
               FROM system.access.table_lineage
               WHERE event_date >= current_date() - INTERVAL 7 DAYS AND entity_type IS NOT NULL AND ({in_scope})
               GROUP BY 1, 2, 3, 4)
        SELECT '{snapshot_id}' AS snapshot_id, current_timestamp() AS snapshot_at, e.*,
               coalesce(j.name, p.name) AS entity_name, '{args.run_id}' AS run_id
        FROM edges e
        LEFT JOIN jobs j ON e.entity_type = 'JOB' AND e.entity_id = j.job_id
        LEFT JOIN pipes p ON e.entity_type = 'PIPELINE' AND e.entity_id = p.pipeline_id""")

    previous_id = None
    if spark.catalog.tableExists(snapshot_t):
        last = spark.sql(f"SELECT snapshot_id FROM {snapshot_t} ORDER BY snapshot_at DESC LIMIT 1").collect()
        previous_id = last[0]["snapshot_id"] if last else None
    # Write first, then diff the stored snapshot (serverless has no cache, and lineage keeps arriving).
    current.write.mode("append").saveAsTable(snapshot_t)
    current = spark.read.table(snapshot_t).where(F.col("snapshot_id") == snapshot_id)

    keep = ["source", "target", "entity_type", "entity_id", "entity_name", "created_by", "first_seen", "last_seen"]
    data_tables = [f"{n.catalog}.{n.schema(layer)}." for layer in DATA_LAYERS]
    touches_data = F.lit(False)
    for prefix in data_tables:
        touches_data = touches_data | F.col("source").startswith(prefix) | F.col("target").startswith(prefix)
    current = current.where(touches_data)
    if previous_id is None:
        changes = current.select(F.lit("baseline").alias("change"), *keep)
    else:
        previous = spark.read.table(snapshot_t).where((F.col("snapshot_id") == previous_id) & touches_data)
        added = current.join(previous.select(*EDGE), EDGE, "left_anti").select(F.lit("added").alias("change"), *keep)
        gone = previous.join(current.select(*EDGE), EDGE, "left_anti").select(F.lit("not_seen_7d").alias("change"),
                                                                             *keep)
        changes = added.unionByName(gone)
    changes = changes.select(F.current_timestamp().alias("detected_at"), "*",
                             F.lit(snapshot_id).alias("snapshot_id"),
                             F.lit(previous_id).cast("string").alias("previous_snapshot_id"),
                             F.lit(args.run_id).alias("run_id"))

    changes.write.mode("append").saveAsTable(changelog_t)
    summary = {r["change"]: r["n"] for r in changes.groupBy("change").agg(F.count("*").alias("n")).collect()}
    print(f"snapshot {snapshot_id}: {current.count()} data-layer edges; previous {previous_id}; changes {summary}")
    for r in changes.where("change <> 'baseline'").collect():
        print(f"  {r['change']}: {r['source'] or '-'} -> {r['target'] or '-'} by {r['entity_type']} "
              f"{r['entity_name'] or r['entity_id']} ({r['created_by']}, first seen {r['first_seen']})")


if __name__ == "__main__":
    main()
