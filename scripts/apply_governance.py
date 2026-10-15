"""Apply PII governance and access grants to a bundle target (T04; idempotent).

1. Tags: ABAC keys on Data Classification's own system tags (class.email_address, class.sg_nric, ...).
   With --manual-tags they are also set from each contract's `pii` fields, as the fallback when the
   classification scan has not finished. The market column gets the governed tag row_scope=country
   (reused: this sandbox account has reached its tag-policy limit, so no new governed tags).
2. Classification status: which PII columns the scan has tagged so far (time-to-tag evidence).
3. Mask and filter functions in the gov schema.
4. ABAC policies on the catalog (GA): mask contact details, restrict identifiers, filter rows by
   market. Pipeline and index-sync principals are excepted, or their refreshes would read masked data.
   The mask also matches Data Classification's own tags, so a newly classified column is masked with
   no change here.
5. Grants from config/access_matrix.csv, and CAN_USE on the SQL warehouse for the persona groups.

    uv run --group dbx python scripts/apply_governance.py --target dev
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel

from meridian.common.bundle import target_names
from meridian.common.pii import CLASS_TAGS
from meridian.common.workspace import sql, warehouse_id
from meridian.contracts.compiler import load_all

REPO = Path(__file__).resolve().parents[1]
PERSONA_GROUPS = ["meridian-support", "meridian-finance", "meridian-de", "meridian-admin"]
SCOPE_TAG, SCOPE_VALUE = "row_scope", "country"


def expand(w: WorkspaceClient, catalog: str, securable_type: str, securable: str) -> list[str]:
    """Securables a matrix row names. READ SECRET is granted per secret (privilege model 1.0 has no
    schema-level READ SECRET), so "secrets.*" means every secret in that schema at apply time."""
    if securable_type != "SECRET":
        return [securable]
    if not securable.endswith(".*"):
        return [f"{catalog}.{securable}"]
    schema = securable[:-2]
    if not schema_exists(w, f"{catalog}.{schema}"):
        print(f"skipped {catalog}.{schema}.*: schema does not exist yet")
        return []
    return [s.full_name for s in w.secrets_uc.list_secrets(catalog_name=catalog, schema_name=schema)]


def schema_exists(w: WorkspaceClient, full_name: str) -> bool:
    try:
        w.schemas.get(full_name)
        return True
    except NotFound:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="dev")
    parser.add_argument("--manual-tags", action="store_true", help="set class.* tags from the contracts")
    args = parser.parse_args()
    names = target_names(args.target)
    w = WorkspaceClient()
    catalog, prefix = names.catalog, names.schemas["bronze"][: -len("bronze")]
    gov = f"{catalog}.{names.schemas['gov']}"
    ci = next(sp.application_id for sp in w.service_principals.list(filter='displayName eq "meridian-ci"'))
    exempt = f"`meridian-admin`, `{ci}`"  # admins, and the principal that runs staging and prod pipelines

    contracts = load_all()
    for contract in contracts.values():
        table = names.table("silver", contract.dataset)
        existing = {(r[0], r[1]) for r in sql(w, f"SELECT column_name, tag_name FROM {catalog}.information_schema.column_tags "
                                              f"WHERE schema_name = '{names.schemas['silver']}' "
                                              f"AND table_name = '{contract.dataset}' AND tag_name LIKE 'class.%'")}
        for column, category in contract.pii_columns().items():
            tag = CLASS_TAGS.get(category)
            if column == "notes" or tag is None:
                continue  # raw notes never reach silver; notes_redacted carries no PII
            state = "auto-tagged" if (column, tag) in existing else "not tagged yet"
            if args.manual_tags and (column, tag) not in existing:
                sql(w, f"ALTER TABLE {table} ALTER COLUMN {column} SET TAGS ('{tag}')")
                state = "tagged manually"
            print(f"  {table}.{column}: {tag} ({state})")
    sql(w, f"ALTER TABLE {names.table('silver', 'payments')} ALTER COLUMN country "
           f"SET TAGS ('{SCOPE_TAG}' = '{SCOPE_VALUE}')")

    for statement in [
        f"""CREATE OR REPLACE FUNCTION {gov}.mask_contact(v STRING) RETURNS STRING
            COMMENT 'ABAC mask: first letter and domain of an email, last 4 digits of a phone'
            RETURN CASE WHEN v IS NULL THEN NULL
                        WHEN v LIKE '%@%' THEN concat(left(v, 1), '***@', substring_index(v, '@', -1))
                        ELSE concat('**** ', right(v, 4)) END""",
        f"""CREATE OR REPLACE FUNCTION {gov}.restrict_string(v STRING) RETURNS STRING
            COMMENT 'ABAC restriction: identifiers are hidden entirely' RETURN CAST(NULL AS STRING)""",
        f"""CREATE OR REPLACE FUNCTION {gov}.restrict_date(v DATE) RETURNS DATE
            COMMENT 'ABAC restriction for dates of birth' RETURN CAST(NULL AS DATE)""",
        f"""CREATE OR REPLACE FUNCTION {gov}.in_home_market(country STRING) RETURNS BOOLEAN
            COMMENT 'ABAC row filter: home-market (SG) rows only' RETURN country = 'SG'""",
    ]:
        sql(w, statement)

    policies = {
        "meridian_mask_contact": f"""
            COMMENT 'Mask emails and phones for everyone but admins and pipeline principals'
            COLUMN MASK {gov}.mask_contact TO `account users` EXCEPT {exempt} FOR TABLES
            MATCH COLUMNS has_tag('class.email_address') OR has_tag('class.phone_number') AS col
            ON COLUMN col""",
        "meridian_restrict_identifiers": f"""
            COMMENT 'Hide national IDs (NRIC) and card numbers from everyone but admins and pipelines'
            COLUMN MASK {gov}.restrict_string TO `account users` EXCEPT {exempt} FOR TABLES
            MATCH COLUMNS has_tag('class.sg_nric') OR has_tag('class.sg_fin') OR has_tag('class.credit_card') AS col
            ON COLUMN col""",
        "meridian_restrict_dob": f"""
            COMMENT 'Hide dates of birth from everyone but admins and pipelines'
            COLUMN MASK {gov}.restrict_date TO `account users` EXCEPT {exempt} FOR TABLES
            MATCH COLUMNS has_tag('class.date_of_birth') AS col ON COLUMN col""",
        "meridian_home_market": f"""
            COMMENT 'Support agents see home-market payments only; finance and admins see all markets'
            ROW FILTER {gov}.in_home_market TO `meridian-support` EXCEPT `meridian-finance`, `meridian-admin`
            FOR TABLES MATCH COLUMNS has_tag_value('{SCOPE_TAG}', '{SCOPE_VALUE}') AS market USING COLUMNS (market)""",
    }
    for name, body in policies.items():
        sql(w, f"CREATE OR REPLACE POLICY {name} ON CATALOG {catalog} {body}")
    print(f"ABAC policies on {catalog}: {', '.join(policies)}")

    with open(REPO / "config" / "access_matrix.csv") as fh:
        for row in csv.DictReader(fh):
            if row["targets"] and args.target not in row["targets"].split(","):
                continue
            securable = row["securable"].format(catalog=catalog, prefix=prefix)
            if row["securable_type"] == "SCHEMA":
                securable = f"{catalog}.{securable}"
                if not schema_exists(w, securable):
                    print(f"skipped {securable}: schema does not exist yet")
                    continue
            privileges = ", ".join(p.replace("_", " ") for p in row["privileges"].split("|"))
            for target in expand(w, catalog, row["securable_type"], securable):
                if row["securable_type"] == "SECRET":  # SQL GRANT ON SECRET fails on the warehouse here
                    w.api_client.do("PATCH", f"/api/2.1/unity-catalog/permissions/secret/{target}", body={
                        "changes": [{"principal": row["principal"], "add": row["privileges"].split("|")}]})
                else:
                    sql(w, f"GRANT {privileges} ON {row['securable_type']} {target} TO `{row['principal']}`")
    print("grants applied from config/access_matrix.csv")

    wh = warehouse_id(w)
    w.warehouses.update_permissions(wh, access_control_list=[
        WarehouseAccessControlRequest(group_name=g, permission_level=WarehousePermissionLevel.CAN_USE)
        for g in PERSONA_GROUPS
    ])
    print(f"CAN_USE on warehouse {wh} for {', '.join(PERSONA_GROUPS)}")


if __name__ == "__main__":
    main()
