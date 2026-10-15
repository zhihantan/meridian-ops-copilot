"""Customers: CDC events -> validated view -> SCD1 and SCD2 through AUTO CDC (T03, T04, T05).

Native: AUTO CDC (sequencing, deletes, SCD2 history), Auto Loader addNewColumns schema evolution.
BUILD: free-text redaction of `notes` and the quarantine table. Raw `notes` never reaches silver.
"""

import sys

from pyspark import pipelines as dp
from pyspark.sql import functions as F

sys.path.insert(0, spark.conf.get("meridian.src_dir"))  # noqa: F821  bundle-synced src/ folder
from meridian.common import pii
from meridian.pipelines.settings import Settings

s = Settings(spark)  # noqa: F821
contract = s.contract("customers")
cdc = contract.cdc
META_COLUMNS = ["_rescued_data", "_source_file", "_file_modified_at", "_ingested_at", "_failed_rules"]


@dp.table(
    name=s.table("bronze", "customers_changes"),
    comment="Raw customer CDC events (op I/U/D with seq) from Auto Loader.",
    table_properties={"quality": "bronze"},
)
def bronze_customers_changes():
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", contract.format)
        .option("cloudFiles.schemaEvolutionMode", s.option("customers.schema_evolution_mode", "addNewColumns"))
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


@dp.temporary_view(name="customers_validated")
@dp.expect_all(contract.expectations())
@dp.expect_all_or_fail(contract.fail_expectations())
def customers_validated():
    redacted = F.col("notes")
    for kind, pattern in pii.PATTERNS.items():
        redacted = F.regexp_replace(redacted, pattern, pii.TOKENS[kind])
    return (
        spark.readStream.table(s.table("bronze", "customers_changes"))  # noqa: F821
        .withColumn("_failed_rules", F.expr(contract.failed_rules_sql()))
        .withColumn("notes_redacted", redacted)
        .withColumn("contains_pii", F.coalesce(F.col("notes") != redacted, F.lit(False)))
    )


@dp.temporary_view(name="customers_valid")
def customers_valid():
    return spark.readStream.table("customers_validated").where("size(_failed_rules) = 0")  # noqa: F821


for target, scd_type, comment in [
    ("customers", 1, "Current customer records (SCD type 1). Raw notes are replaced by notes_redacted."),
    ("customers_history", 2, "Full customer history (SCD type 2) with __START_AT and __END_AT."),
]:
    dp.create_streaming_table(name=s.table("silver", target), comment=comment, table_properties={"quality": "silver"})
    dp.create_auto_cdc_flow(
        target=s.table("silver", target),
        source="customers_valid",
        keys=[contract.key],
        sequence_by=F.col(cdc["sequence_column"]),
        apply_as_deletes=F.expr(f"{cdc['operation_column']} = '{cdc['delete_value']}'"),
        except_column_list=[cdc["operation_column"], "notes", *META_COLUMNS],
        stored_as_scd_type=scd_type,
    )


@dp.table(
    name=s.table("quarantine", "customers"),
    comment="BUILD: customer events that failed a quarantine rule (for example a card number in notes).",
    table_properties={"quality": "quarantine"},
)
def quarantine_customers():
    return (
        spark.readStream.table("customers_validated")  # noqa: F821
        .where("size(_failed_rules) > 0")
        .drop("notes")
        .withColumn("severity", F.expr(contract.rule_severity_sql()))
        .withColumn("_quarantined_at", F.current_timestamp())
    )
