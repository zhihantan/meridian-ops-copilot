"""Resolve a bundle target's catalog and schema names from `databricks bundle validate -o json`."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetNames:
    target: str
    catalog: str
    schemas: dict[str, str]

    def table(self, schema: str, name: str) -> str:
        return f"{self.catalog}.{self.schemas[schema]}.{name}"


def target_names(target: str) -> TargetNames:
    out = subprocess.run(["databricks", "bundle", "validate", "-t", target, "-o", "json"],
                         capture_output=True, text=True, check=True).stdout
    config = json.loads(out)
    return TargetNames(
        target=target,
        catalog=config["variables"]["catalog"]["value"],
        schemas={key: s["name"] for key, s in config["resources"]["schemas"].items()},
    )
