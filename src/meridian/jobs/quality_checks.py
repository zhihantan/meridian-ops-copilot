"""Quality checks that run after each ingest (T04, T05): drift, freshness and PII coverage.

BUILD: an independent drift check against the contract's baseline (also a cross-check for the native
Data Quality Monitoring metrics), a freshness check from the contract's max_delay_minutes, and a PII
coverage register. Each writes events to obs/gov tables. With --fail-on-breach the task fails on a
breach, so the job's AT_LEAST_ONE_FAILED escalation path runs.

    quality_checks.py --check drift|freshness|pii_coverage --catalog C --bronze-schema S [--fail-on-breach]
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from meridian.common.pii import COVERED_TAGS
from meridian.contracts.compiler import load_all
from meridian.jobs.common import Names, names, parser

EVENT_SCHEMA = (
    "event_id STRING, check_name STRING, checked_at TIMESTAMP, dataset STRING, table_name STRING, "
    "column_name STRING, metric STRING, group_key STRING, baseline_value DOUBLE, current_value DOUBLE, "
    "threshold DOUBLE, breached BOOLEAN, message STRING, run_id STRING"
)
PII_NAME_HINTS = ("email", "phone", "mobile", "nric", "national_id", "passport", "card", "dob", "birth", "address")


def event(check: str, run_id: str, **fields) -> dict:
    return {"event_id": str(uuid.uuid4()), "check_name": check, "checked_at": datetime.now(UTC),
            "run_id": run_id, "baseline_value": None, **fields}


def windows(newest, drift: dict):
    window_start = F.lit(newest) - F.expr(f"INTERVAL {drift['window_hours']} HOURS")
    return window_start, window_start - F.expr(f"INTERVAL {drift['baseline_days']} DAYS")


def check_drift(spark: SparkSession, n: Names, contract, run_id: str) -> list[dict]:
    """Last 24h vs the baseline window: failure rate per acquirer (ratio) and null rate per column (pp)."""
    drift, ts = contract.drift, contract.event_time_column
    silver, bronze = spark.read.table(n.table("silver", "payments")), spark.read.table(n.table("bronze", "payments"))
    window_start, baseline_start = windows(silver.agg(F.max(ts)).first()[0], drift)

    def labelled(df):
        return (df.withColumn("window", F.when(F.col(ts) >= window_start, "current")
                              .when(F.col(ts) >= baseline_start, "baseline")).where("window IS NOT NULL"))

    rows = []
    for metric in drift["metrics"]:
        if metric["name"] == "failure_rate_by_acquirer":
            key = metric["group_by"]
            stats: dict[str, dict] = {}
            for r in labelled(silver).groupBy(key, "window").agg(
                    F.avg(F.when(F.col("status") == "failed", 1.0).otherwise(0.0)).alias("rate"),
                    F.count("*").alias("n")).collect():
                stats.setdefault(r[key], {})[r["window"]] = (r["rate"], r["n"])
            for group, w in sorted(stats.items()):
                if "baseline" not in w or "current" not in w or w["current"][1] < metric["min_rows"]:
                    continue
                base, cur = w["baseline"][0], w["current"][0]
                limit = base * metric["max_ratio_to_baseline"]
                rows.append(event("drift", run_id, dataset=contract.dataset, table_name=n.table("silver", "payments"),
                                  column_name="status", metric="failure_rate", group_key=f"{key}={group}",
                                  baseline_value=round(base, 4), current_value=round(cur, 4), threshold=round(limit, 4),
                                  breached=cur > limit,
                                  message=f"failure_rate for {group} is {cur:.1%} vs baseline {base:.1%} "
                                          f"(limit {metric['max_ratio_to_baseline']}x baseline)"))
        if metric["name"] == "null_rate":
            for column in metric["columns"]:
                stats = {r["window"]: r["rate"] * 100 for r in labelled(bronze).groupBy("window").agg(
                    F.avg(F.when(F.col(column).isNull(), 1.0).otherwise(0.0)).alias("rate")).collect()}
                if "baseline" not in stats or "current" not in stats:
                    continue
                base, cur = stats["baseline"], stats["current"]
                limit = base + metric["max_increase_pp"]
                rows.append(event("drift", run_id, dataset=contract.dataset, table_name=n.table("bronze", "payments"),
                                  column_name=column, metric="null_rate_pct", group_key="all",
                                  baseline_value=round(base, 2), current_value=round(cur, 2), threshold=round(limit, 2),
                                  breached=cur > limit,
                                  message=f"null rate of {column} is {cur:.1f}% vs baseline {base:.1f}% "
                                          f"(limit +{metric['max_increase_pp']}pp)"))

    # Schema drift: rows whose values did not fit the reference schema (Auto Loader rescued data).
    rescued = bronze.where("_rescued_data IS NOT NULL")
    count = rescued.count()
    sample = rescued.select("_rescued_data").limit(1).collect()
    rows.append(event("drift", run_id, dataset=contract.dataset, table_name=n.table("bronze", "payments"),
                      column_name="_rescued_data", metric="rescued_rows", group_key="all", baseline_value=0.0,
                      current_value=float(count), threshold=0.0, breached=count > 0,
                      message=f"{count} rows did not match the reference schema"
                              + (f", e.g. {sample[0]['_rescued_data'][:120]}" if sample else "")))
    return rows


def check_freshness(spark: SparkSession, n: Names, contract, run_id: str) -> list[dict]:
    newest = spark.read.table(n.table("bronze", "payments")).agg(F.max(contract.event_time_column)).first()[0]
    lag = (datetime.now(UTC) - newest.replace(tzinfo=UTC)).total_seconds() / 60 if newest else float("inf")
    return [event("freshness", run_id, dataset=contract.dataset, table_name=n.table("bronze", "payments"),
                  column_name=contract.event_time_column, metric="minutes_since_last_event", group_key="all",
                  current_value=round(lag, 1), threshold=float(contract.max_delay_minutes),
                  breached=lag > contract.max_delay_minutes,
                  message=f"no {contract.dataset} event for {lag:.0f} min (limit {contract.max_delay_minutes} min)")]


def check_pii_coverage(spark: SparkSession, n: Names, contract, run_id: str) -> list[dict]:
    """Every PII-looking column must have a reviewed strategy in the contract, or a classification tag
    that an ABAC policy covers. A new PII-looking column (for example secondary_email) has neither until
    Data Classification tags it, so it is flagged in that window.
    """
    target = n.table("silver", contract.dataset)
    tags: dict[str, set[str]] = {}
    for r in spark.sql(f"SELECT column_name, tag_name FROM {n.catalog}.information_schema.column_tags "
                       f"WHERE schema_name = '{n.schema('silver')}' AND table_name = '{contract.dataset}' "
                       "AND tag_name LIKE 'class.%'").collect():
        tags.setdefault(r["column_name"], set()).add(r["tag_name"])
    rows = []
    for field in spark.read.table(target).schema.fields:
        strategy = contract.pii_handling.get(field.name)
        column_tags = tags.get(field.name, set())
        if not column_tags and strategy is None and not any(h in field.name.lower() for h in PII_NAME_HINTS):
            continue
        covered = sorted(column_tags & COVERED_TAGS)
        protected = strategy is not None or bool(covered)
        rows.append(event("pii_coverage", run_id, dataset=contract.dataset, table_name=target, column_name=field.name,
                          metric="protected", group_key=",".join(sorted(column_tags)) or "untagged",
                          current_value=1.0 if protected else 0.0, threshold=1.0, breached=not protected,
                          message=f"{target}.{field.name}: tags {sorted(column_tags) or 'none'}, strategy "
                                  f"{strategy or 'none'}" + ("" if protected else ": PII-like column with no protection")))
    return rows


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--check", required=True, choices=["drift", "freshness", "pii_coverage"])
    p.add_argument("--fail-on-breach", action="store_true")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    contracts = load_all()

    if args.check == "drift":
        rows, target = check_drift(spark, n, contracts["payments"], args.run_id), n.table("obs", "drift_events")
    elif args.check == "freshness":
        rows, target = check_freshness(spark, n, contracts["payments"], args.run_id), n.table("obs", "freshness_events")
    else:
        rows, target = check_pii_coverage(spark, n, contracts["customers"], args.run_id), n.table("gov", "pii_coverage")

    spark.sql(f"CREATE TABLE IF NOT EXISTS {target} ({EVENT_SCHEMA})")
    if rows:
        spark.createDataFrame(rows, EVENT_SCHEMA).write.mode("append").saveAsTable(target)
    breached = [r for r in rows if r["breached"]]
    print(f"{args.check}: {len(rows)} checks, {len(breached)} breached -> {target}")
    for r in breached:
        print("  BREACH", r["message"])
    if breached and args.fail_on_breach:
        raise SystemExit(f"{args.check}: {len(breached)} breach(es)")


if __name__ == "__main__":
    main()
