"""Payments: Auto Loader bronze -> validated view -> silver and quarantine (T03, T05).

Native: Auto Loader with schema hints and rescued data, expectations and their event-log metrics.
BUILD: the quarantine table (flag-column pattern) and the duplicate register. Every rule, hint and
severity comes from contracts/payments.yaml through the contract compiler.
"""

import sys

from pyspark import pipelines as dp
from pyspark.sql import functions as F

sys.path.insert(0, spark.conf.get("meridian.src_dir"))  # noqa: F821  bundle-synced src/ folder
from meridian.pipelines.settings import Settings

s = Settings(spark)  # noqa: F821
contract = s.contract("payments")


@dp.table(
    name=s.table("bronze", "payments"),
    comment="Raw payments from Auto Loader, with rescued data and ingestion metadata.",
    table_properties={"quality": "bronze"},
)
def bronze_payments():
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", contract.format)
        .option("cloudFiles.schemaEvolutionMode", s.option("payments.schema_evolution_mode", "rescue"))
        .option("cloudFiles.schemaHints", contract.schema_hints())
        .option("cloudFiles.inferColumnTypes", "true")
        .load(f"{s.landing_root}/{contract.landing_path}")
        .select(
            "*",
            F.col("_metadata.file_path").alias("_source_file"),
            F.col("_metadata.file_modification_time").alias("_file_modified_at"),
            F.current_timestamp().alias("_ingested_at"),
        )
    )


@dp.temporary_view(name="payments_validated")
@dp.expect_all(contract.expectations())
@dp.expect_all_or_fail(contract.fail_expectations())
def payments_validated():
    return spark.readStream.table(s.table("bronze", "payments")).withColumn(  # noqa: F821
        "_failed_rules", F.expr(contract.failed_rules_sql())
    )


@dp.table(
    name=s.table("silver", "payments"),
    comment="Payments that passed every contract rule; one row per payment_id.",
    table_properties={"quality": "silver"},
)
def silver_payments():
    unique = contract.uniqueness
    return (
        spark.readStream.table("payments_validated")  # noqa: F821
        .where("size(_failed_rules) = 0")
        .withWatermark(contract.event_time_column, unique["watermark"])
        .dropDuplicatesWithinWatermark(unique["columns"])
        .drop("_failed_rules", "_rescued_data")
    )


@dp.table(
    name=s.table("quarantine", "payments"),
    comment="BUILD: rows that failed a quarantine rule, with rule names, severity, source file and time.",
    table_properties={"quality": "quarantine"},
)
def quarantine_payments():
    return (
        spark.readStream.table("payments_validated")  # noqa: F821
        .where("size(_failed_rules) > 0")
        .withColumn("severity", F.expr(contract.rule_severity_sql()))
        .withColumn("_quarantined_at", F.current_timestamp())
        .withColumn("reprocessed_at", F.lit(None).cast("timestamp"))
    )


@dp.materialized_view(
    name=s.table("quarantine", "payment_duplicates"),
    comment="BUILD: payment_id values seen more than once in bronze. Silver keeps a single copy.",
)
def payment_duplicates():
    unique = contract.uniqueness
    return (
        spark.read.table(s.table("bronze", "payments"))  # noqa: F821
        .where("payment_id IS NOT NULL")
        .groupBy(*unique["columns"])
        .agg(
            F.count("*").alias("copies"),
            F.collect_set("_source_file").alias("source_files"),
            F.max("_ingested_at").alias("last_seen_at"),
        )
        .where("copies > 1")
        .withColumn("rule", F.lit(unique["name"]))
        .withColumn("severity", F.lit(unique["severity"]))
    )
