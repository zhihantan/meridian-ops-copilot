"""Shared helpers for job scripts that run as serverless Python file tasks.

Jobs get the catalog and the resolved bronze schema name. Every layer shares that schema's prefix
("" in staging and prod, "dev_<user>_" in development mode), so one argument covers all layers.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import dataclass

LAYERS = ("landing", "bronze", "silver", "quarantine", "gold", "obs", "gov", "kb", "agent", "eval")


@dataclass(frozen=True)
class Names:
    catalog: str
    prefix: str

    def schema(self, layer: str) -> str:
        return f"{self.prefix}{layer}"

    def table(self, layer: str, name: str) -> str:
        return f"{self.catalog}.{self.prefix}{layer}.{name}"


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--catalog", required=True)
    p.add_argument("--bronze-schema", required=True, help="resolved bronze schema; its prefix applies to every layer")
    p.add_argument("--run-id", default="manual")
    p.add_argument("--src-dir", help="bundle-synced src/ folder (read before imports)")
    return p


def names(args) -> Names:
    if not args.bronze_schema.endswith("bronze"):
        raise ValueError(f"unexpected bronze schema name {args.bronze_schema}")
    return Names(args.catalog, args.bronze_schema[: -len("bronze")])


def read_uc_secret(full_name: str) -> str | None:
    """Value of a Unity Catalog secret (PREVIEW), read as the job's identity. None if missing."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    try:
        secret = w.api_client.do("GET", f"/api/2.1/unity-catalog/secrets/{full_name}", query={"include_value": "true"})
    except Exception as exc:  # noqa: BLE001  missing secret or no READ privilege: degrade to logs
        print(f"secret {full_name} not readable: {exc}")
        return None
    return secret.get("effective_value")


def post_slack(token: str | None, channel: str, text: str) -> None:
    """Post with the Slack bot token (BUILD). Without a token the message only goes to the job log."""
    print(text)
    if not token:
        return
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "text": text}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
    if not body.get("ok"):
        raise RuntimeError(f"Slack error: {body.get('error')}")
