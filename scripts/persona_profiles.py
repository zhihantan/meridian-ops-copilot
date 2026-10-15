"""Write local CLI profiles (meridian-ava, meridian-ben, meridian-gus) for the persona service principals.

Each profile gets a fresh OAuth M2M secret, written straight into ~/.databrickscfg and never printed,
so scripts and Claude Code can act as that persona. Existing profiles are kept unless --rotate.

    uv run --group dbx python scripts/persona_profiles.py [--rotate]
"""

from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path

from databricks.sdk import WorkspaceClient

PERSONAS = {"meridian-ava": "meridian-ava", "meridian-ben": "meridian-ben", "meridian-gus": "meridian-gus"}
CONFIG = Path(os.environ.get("DATABRICKS_CONFIG_FILE", Path.home() / ".databrickscfg"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument("--lifetime", default=f"{30 * 24 * 3600}s", help="secret lifetime, default 30 days")
    args = parser.parse_args()

    w = WorkspaceClient()
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG)
    for profile, display_name in PERSONAS.items():
        if profile in cfg and not args.rotate:
            print(f"{profile}: exists (use --rotate to replace)")
            continue
        sp = next(iter(w.service_principals.list(filter=f'displayName eq "{display_name}"')))
        secret = w.service_principal_secrets_proxy.create(service_principal_id=sp.id, lifetime=args.lifetime)
        cfg[profile] = {"host": w.config.host, "client_id": sp.application_id, "client_secret": secret.secret}
        print(f"{profile}: written for {display_name} (secret not shown)")
    with open(CONFIG, "w") as fh:
        cfg.write(fh)
    CONFIG.chmod(0o600)


if __name__ == "__main__":
    main()
