"""Gold tables designed for their consumers: Genie, the ops agent and the dashboard (T03, T22)."""

import sys

from pyspark import pipelines as dp
from pyspark.sql import functions as F

sys.path.insert(0, spark.conf.get("meridian.src_dir"))  # noqa: F821  bundle-synced src/ folder
from meridian.pipelines.settings import DISPLAY_TZ, Settings

s = Settings(spark)  # noqa: F821
failed = F.when(F.col("status") == "failed", 1).otherwise(0)


def _payments():
    return spark.read.table(s.table("silver", "payments")).withColumn(  # noqa: F821
        "local_ts", F.from_utc_timestamp("created_at", DISPLAY_TZ)
    )


@dp.materialized_view(
    name=s.table("gold", "payment_failure_daily"),
    comment="Daily payment counts and failure rate per acquirer, Singapore time.",
)
def payment_failure_daily():
    return (
        _payments()
        .groupBy(F.to_date("local_ts").alias("payment_date"), "acquirer_id")
        .agg(F.count("*").alias("payments"), F.sum(failed).alias("failed_payments"))
        .withColumn("failure_rate", F.round(F.col("failed_payments") / F.col("payments"), 4))
    )


@dp.materialized_view(
    name=s.table("gold", "acquirer_hourly"),
    comment="Hourly failure rate per acquirer and refundable failed value (issuer_unavailable, timeout).",
)
def acquirer_hourly():
    refundable = F.col("status").eqNullSafe("failed") & F.col("failure_code").isin("issuer_unavailable", "timeout")
    return (
        _payments()
        .groupBy(F.date_trunc("hour", "local_ts").alias("hour_sgt"), "acquirer_id", "currency")
        .agg(
            F.count("*").alias("payments"),
            F.sum(failed).alias("failed_payments"),
            F.sum(F.when(refundable, 1).otherwise(0)).alias("refundable_failed_payments"),
            F.sum(F.when(refundable, F.col("amount")).otherwise(0)).alias("refundable_failed_amount"),
        )
        .withColumn("failure_rate", F.round(F.col("failed_payments") / F.col("payments"), 4))
    )


@dp.materialized_view(
    name=s.table("gold", "merchant_daily"),
    comment="Daily volume per merchant and currency.",
)
def merchant_daily():
    return (
        _payments()
        .groupBy(F.to_date("local_ts").alias("payment_date"), "merchant_id", "currency")
        .agg(
            F.count("*").alias("payments"),
            F.sum(failed).alias("failed_payments"),
            F.sum("amount").alias("gross_amount"),
            F.sum(F.when(F.col("status") == "failed", F.col("amount")).otherwise(0)).alias("failed_amount"),
        )
    )
