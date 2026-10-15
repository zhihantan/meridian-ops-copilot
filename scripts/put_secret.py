"""Store a value as a Unity Catalog secret (PREVIEW) in <catalog>.secrets.<name> for each catalog.

The value is read with a hidden prompt, so it never touches shell history, logs or the repo. Run it
again to rotate: the secret is updated in place and jobs pick it up with no redeploy (T08).

    uv run --group dbx python scripts/put_secret.py slack_bot_token --catalogs meridian_dev meridian_staging meridian
"""

from __future__ import annotations

import argparse
import getpass

from databricks.sdk import WorkspaceClient
from databricks.sdk.common.types.fieldmask import FieldMask
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import Secret

SCHEMA = "secrets"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="secret name, e.g. slack_bot_token or slack_webhook_url")
    parser.add_argument("--catalogs", nargs="+", required=True)
    parser.add_argument("--comment", default="Meridian demo Slack app credential")
    args = parser.parse_args()

    value = getpass.getpass(f"Value for {args.name} (input hidden): ").strip()
    if not value:
        raise SystemExit("empty value, nothing stored")

    w = WorkspaceClient()
    for catalog in args.catalogs:
        full_name = f"{catalog}.{SCHEMA}.{args.name}"
        try:
            w.schemas.get(f"{catalog}.{SCHEMA}")
        except NotFound:
            w.schemas.create(name=SCHEMA, catalog_name=catalog, comment="Credentials owned by the platform team")
        try:
            w.secrets_uc.get_secret(full_name)
            w.secrets_uc.update_secret(full_name, Secret(value=value), update_mask=FieldMask(["value"]))
            print(f"rotated {full_name}")
        except NotFound:
            w.secrets_uc.create_secret(Secret(name=args.name, catalog_name=catalog, schema_name=SCHEMA,
                                              value=value, comment=args.comment))
            print(f"created {full_name}")


if __name__ == "__main__":
    main()
