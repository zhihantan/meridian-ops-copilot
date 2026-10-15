"""Pipeline settings resolved from the pipeline configuration that the bundle writes.

Schema names come from bundle resource references, so development-mode prefixes (one set of schemas
per developer) never have to be reconstructed in code.
"""

from __future__ import annotations

from meridian.contracts.compiler import Contract, load_contract

DISPLAY_TZ = "Asia/Singapore"


class Settings:
    def __init__(self, spark):
        conf = spark.conf
        self.catalog = conf.get("meridian.catalog")
        self.landing_root = conf.get("meridian.landing_root")
        self.contracts_dir = conf.get("meridian.contracts_dir")
        self._conf = conf

    def table(self, schema: str, name: str) -> str:
        """Fully qualified table name; `schema` is a logical layer such as 'silver'."""
        return f"{self.catalog}.{self._conf.get(f'meridian.schema.{schema}')}.{name}"

    def option(self, key: str, default: str) -> str:
        return self._conf.get(f"meridian.{key}", default)

    def contract(self, dataset: str) -> Contract:
        return load_contract(f"{self.contracts_dir}/{dataset}.yaml")
