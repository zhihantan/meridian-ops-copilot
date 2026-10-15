"""Quality checks that run after each ingest (T04, T05): drift, freshness and PII coverage.

BUILD: an independent drift check against the contract's baseline (also a cross-check for the native
Data Quality Monitoring metrics), a freshness check from the contract's max_delay_minutes, and a PII
coverage register. Each writes rows to obs/gov tables; SQL alerts on those tables send the notifications.

Runs as a serverless job task:  python quality_checks.py --check drift|freshness|pii_coverage ...
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def table(args, schema_key: str, name: str) -> str:
    return f"{args.catalog}.{getattr(args, f'schema_{schema_key}')}.{name}"


def write_events(spark: SparkSession, target: str, rows: list[dict]) -> None:
    schema = ("event_id STRING, check_name STRING, checked_at TIMESTAMP, dataset STRING, table_name STRING, "
              "column_name STRING, metric STRING, group_key STRING, baseline_value DOUBLE, current_value DOUBLE, "
              "threshold DOUBLE, breached BOOLEAN, message STRING, run_id STRING")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {target} ({schema})")
    if rows:
        spark.createDataFrame(rows, schema).write.mode("append").saveAsTable(target)


def event(check: str, run_id: str, **fields) -> dict:
    base = {"event_id": str(uuid.uuid4()), "check_name": check, "checked_at": datetime.now(UTC), "run_id": run_id}
    return {**base, **fields}


def check_drift(spark: SparkSession, args, contract) -> list[dict]:
    """Last 24h vs the baseline window: failure rate per acquirer (ratio) and null rate per column (pp)."""
    drift = contract.drift
    silver = spark.read.table(table(args, "silver", "payments"))
    bronze = spark.read.table(table(args, "bronze", "payments"))
    ts = contract.event_time_column
    newest = silver.agg(F.max(ts)).first()[0]
    window_start = F.lit(newest) - F.expr(f"INTERVAL {drift['window_hours']} HOURS")
    baseline_start = window_start - F.expr(f"INTERVAL {drift['baseline_days']} DAYS")
    rows = []

    for metric in drift["metrics"]:
        if metric["name"] == "failure_rate_by_acquirer":
            failed = F.avg(F.when(F.col("status") == "failed", 1.0).otherwise(0.0))
            stats = (silver.withColumn("window", F.when(F.col(ts) >= window_start, "current")
                                       .when(F.col(ts) >= baseline_start, "baseline"))
                     .where("window IS NOT NULL").groupBy(metric["group_by"], "window")
                     .agg(failed.alias("rate"), F.count("*").alias("n")).collect())
            by_group: dict[str, dict] = {}
            for r in stats:
                by_group.setdefault(r[metric["group_by"]], {})[r["window"]] = (r["rate"], r["n"])
            for group, w in sorted(by_group.items()):
                if "baseline" not in w or "current" not in w or w["current"][1] < metric["min_rows"]:
                    continue
                (base, _), (cur, _) = w["baseline"], w["current"]
                limit = base * metric["max_ratio_to_baseline"]
                rows.append(event("drift", args.run_id, dataset=contract.dataset, table_name=table(args, "silver", "payments"),
                                  column_name="status", metric="failure_rate", group_key=f"{metric['group_by']}={group}",
                                  baseline_value=round(base, 4), current_value=round(cur, 4), threshold=round(limit, 4),
                                  breached=cur > limit,
                                  message=f"failure_rate for {group} is {cur:.1%} vs baseline {base:.1%} "
                                          f"(limit {metric['max_ratio_to_baseline']}x)"))
        if metric["name"] == "null_rate":
            for column in metric["columns"]:
                nulls = F.avg(F.when(F.col(column).isNull(), 1.0).otherwise(0.0))
                stats = {r["window"]: r["rate"] for r in (
                    bronze.withColumn("window", F.when(F.col(ts) >= window_start, "current")
                                      .when(F.col(ts) >= baseline_start, "baseline"))
                    .where("window IS NOT NULL").groupBy("window").agg(nulls.alias("rate")).collect())}
                if "baseline" not in stats or "current" not in stats:
                    continue
                base, cur = stats["baseline"] * 100, stats["current"] * 100
                limit = base + metric["max_increase_pp"]
                rows.append(event("drift", args.run_id, dataset=contract.dataset, table_name=table(args, "bronze", "payments"),
                                  column_name=column, metric="null_rate_pct", group_key="all",
                                  baseline_value=round(base, 2), current_value=round(cur, 2), threshold=round(limit, 2),
                                  breached=cur > limit,
                                  message=f"null rate of {column} is {cur:.1f}% vs baseline {base:.1f}% "
                                          f"(limit +{metric['max_increase_pp']}pp)"))

    # Schema drift: rows whose values did not fit the reference schema.
    rescued = bronze.where("_rescued_data IS NOT NULL")
    n = rescued.count()
    sample = rescued.select("_rescued_data").limit(1).collect()
    rows.append(event("drift", args.run_id, dataset=contract.dataset, table_name=table(args, "bronze", "payments"),
                      column_name="_rescued_data", metric="rescued_rows", group_key="all", baseline_value=0.0,
                      current_value=float(n), threshold=0.0, breached=n > 0,
                      message=f"{n} rows did not match the reference schema"
                              + (f"; e.g. {sample[0]['_rescued_data'][:120]}" if sample else "")))
    return rows


def check_freshness(spark: SparkSession, args, contract) -> list[dict]:
    newest = spark.read.table(table(args, "bronze", "payments")).agg(F.max(contract.event_time_column)).first()[0]
    now = datetime.now(UTC)
    lag = (now - newest.replace(tzinfo=UTC)).total_seconds() / 60 if newest else float("inf")
    return [event("freshness", args.run_id, dataset=contract.dataset, table_name=table(args, "bronze", "payments"),
                  column_name=contract.event_time_column, metric="minutes_since_last_event", group_key="all",
                  baseline_value=None, current_value=round(lag, 1), threshold=float(contract.max_delay_minutes),
                  breached=lag > contract.max_delay_minutes,
                  message=f"no {contract.dataset} event for {lag:.0f} min (limit {contract.max_delay_minutes} min)")]


PII_NAME_HINTS = ("email", "phone", "mobile", "nric", "national_id", "passport", "card", "dob", "birth", "address")


def check_pii_coverage(spark: SparkSession, args, contracts) -> list[dict]:
    """Every column that looks like PII must be tagged and protected (a mask, a restriction, or redaction).

    A column is protected when the contract names a strategy for it, or a governed tag that an ABAC
    policy covers is present. A new PII-looking column (for example secondary_email) is flagged.
    """
    rows = []
    for contract in contracts:
        target = table(args, "silver", contract.dataset)
        handled = contract.pii_handling
        tags = {r["column_name"]: r["tag_value"] for r in spark.sql(
            f"SELECT column_name, tag_value FROM {args.catalog}.information_schema.column_tags "
            f"WHERE schema_name = '{args.schema_silver}' AND table_name = '{contract.dataset}' AND tag_name = 'pii'"
        ).collect()}
        for field in spark.read.table(target).schema.fields:
            looks_pii = any(h in field.name.lower() for h in PII_NAME_HINTS)
            strategy = handled.get(field.name)
            if not looks_pii and field.name not in tags:
                continue
            protected = strategy in ("mask", "restrict", "redact") or (field.name in tags and strategy != "none")
            if strategy == "none":
                protected = True  # an explicit, reviewed decision in the contract
            rows.append(event("pii_coverage", args.run_id, dataset=contract.dataset, table_name=target,
                              column_name=field.name, metric="protected", group_key=tags.get(field.name, "untagged"),
                              baseline_value=None, current_value=1.0 if protected else 0.0, threshold=1.0,
                              breached=not protected,
                              message=f"{target}.{field.name}: tag={tags.get(field.name, 'none')}, "
                                      f"strategy={strategy or 'none'}"
                                      + ("" if protected else " -> PII-like column without protection")))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", required=True, choices=["drift", "freshness", "pii_coverage"])
    parser.add_argument("--catalog", required=True)
    for key in ("bronze", "silver", "obs", "gov"):
        parser.add_argument(f"--schema-{key}", dest=f"schema_{key}", required=True)
    parser.add_argument("--src-dir", required=True, help="bundle-synced src/ folder")
    parser.add_argument("--contracts-dir", required=True)
    parser.add_argument("--run-id", default="manual")
    args = parser.parse_args()

    sys.path.insert(0, args.src_dir)
    from meridian.contracts.compiler import load_contract

    spark = SparkSession.builder.getOrCreate()
    payments = load_contract(f"{args.contracts_dir}/payments.yaml")
    if args.check == "drift":
        rows, target = check_drift(spark, args, payments), table(args, "obs", "drift_events")
    elif args.check == "freshness":
        rows, target = check_freshness(spark, args, payments), table(args, "obs", "freshness_events")
    else:
        customers = load_contract(f"{args.contracts_dir}/customers.yaml")
        rows, target = check_pii_coverage(spark, args, [customers]), table(args, "gov", "pii_coverage")
    write_events(spark, target, rows)
    breached = [r for r in rows if r["breached"]]
    print(f"{args.check}: {len(rows)} checks, {len(breached)} breached -> {target}")
    for r in breached:
        print("  BREACH", r["message"])


if __name__ == "__main__":
    main()
