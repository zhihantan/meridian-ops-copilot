"""Store a value as a Unity Catalog secret in <catalog>.secrets.<name> for each catalog (GA since 2026-08-03).

The value is read with a hidden prompt, so it never touches shell history, logs or the repo. Run it
again to rotate: the secret is updated in place and jobs pick it up with no redeploy (T08). For drills,
--generate stores a random value instead and prints only its fingerprint.

    uv run --group dbx python scripts/put_secret.py slack_bot_token --catalogs meridian_dev meridian_staging meridian
    uv run --group dbx python scripts/put_secret.py t08_probe --catalogs meridian_dev --generate
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import secrets

from databricks.sdk import WorkspaceClient
from databricks.sdk.common.types.fieldmask import FieldMask
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import Secret

from meridian.common.localenv import load_local_env

load_local_env()  # the workspace profile from .env.local, not the shell's default profile

SCHEMA = "secrets"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="secret name, e.g. slack_bot_token or slack_webhook_url")
    parser.add_argument("--catalogs", nargs="+", required=True)
    parser.add_argument("--comment", default="Meridian demo Slack app credential")
    parser.add_argument("--generate", action="store_true", help="store a random value (drills); print its fingerprint")
    args = parser.parse_args()

    if args.generate:
        value = secrets.token_urlsafe(32)
        print(f"generated value, fingerprint {hashlib.sha256(value.encode()).hexdigest()[:12]}")
    else:
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
            w.secrets_uc.update_secret(full_name, Secret(name=args.name, catalog_name=catalog, schema_name=SCHEMA,
                                                         value=value), update_mask=FieldMask(["value"]))
            print(f"rotated {full_name}")
        except NotFound:
            w.secrets_uc.create_secret(Secret(name=args.name, catalog_name=catalog, schema_name=SCHEMA,
                                              value=value, comment=args.comment))
            print(f"created {full_name}")


if __name__ == "__main__":
    main()
