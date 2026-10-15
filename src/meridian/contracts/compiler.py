"""Compile data contracts into pipeline settings, alert routing and docs (T03).

The contract YAML is the single source of truth: schema hints, expectations, quarantine rules and
severity routing are all derived here, never copied by hand. Pure Python plus PyYAML, so it runs in
CI, in SDP pipeline code and in jobs alike.

    uv run python -m meridian.contracts.compiler --docs docs/contracts
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
SEVERITIES = ("critical", "warn", "info")
ACTIONS = ("fail", "quarantine", "warn")
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITIES))}  # info 0, warn 1, critical 2


@dataclass(frozen=True)
class Rule:
    name: str
    expr: str
    severity: str
    on_violation: str
    notify: str


@dataclass
class Contract:
    dataset: str
    owner: str
    landing_path: str
    format: str
    max_delay_minutes: int
    event_time_column: str
    key: str
    schema: list[dict]
    rules: list[Rule]
    routing: dict
    uniqueness: dict | None = None
    drift: dict | None = None
    cdc: dict | None = None
    pii_handling: dict = field(default_factory=dict)

    # ---- schema
    def schema_hints(self) -> str:
        """Auto Loader cloudFiles.schemaHints, e.g. 'payment_id STRING, amount DECIMAL(12,2)'."""
        return ", ".join(f"{c['name']} {c['type']}" for c in self.schema)

    def pii_columns(self) -> dict[str, str]:
        return {c["name"]: c["pii"] for c in self.schema if c.get("pii")}

    # ---- expectations
    def expectations(self) -> dict[str, str]:
        """Rules recorded as expectation metrics without stopping the update (warn and quarantine)."""
        return {r.name: r.expr for r in self.rules if r.on_violation != "fail"}

    def fail_expectations(self) -> dict[str, str]:
        """Critical rules: a violation fails the pipeline update."""
        return {r.name: r.expr for r in self.rules if r.on_violation == "fail"}

    def quarantine_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.on_violation == "quarantine"]

    def failed_rules_sql(self, dialect: str = "spark") -> str:
        """SQL expression returning the array of quarantine rules a row fails. NULL counts as a failure."""
        cases = [f"CASE WHEN NOT coalesce(({r.expr}), false) THEN '{r.name}' END" for r in self.quarantine_rules()]
        if dialect == "spark":
            return f"filter(array({', '.join(cases)}), x -> x IS NOT NULL)"
        if dialect == "duckdb":
            return f"list_filter([{', '.join(cases)}], x -> x IS NOT NULL)"
        raise ValueError(f"unknown dialect {dialect}")

    def rule_severity_sql(self) -> str:
        """Spark SQL: highest severity among the failed rules in _failed_rules."""
        whens = []
        for sev in SEVERITIES:
            names = [r.name for r in self.quarantine_rules() if r.severity == sev]
            if names:
                quoted = ", ".join(f"'{n}'" for n in names)
                whens.append(f"WHEN arrays_overlap(_failed_rules, array({quoted})) THEN '{sev}'")
        return f"CASE {' '.join(whens)} END"

    # ---- routing
    def routing_config(self) -> dict[str, dict]:
        """Rules grouped by notification channel, consumed by alert definitions and docs."""
        out: dict[str, dict] = {}
        all_rules = list(self.rules)
        if self.uniqueness:
            u = self.uniqueness
            all_rules.append(Rule(u["name"], f"unique({', '.join(u['columns'])})", u["severity"],
                                  "quarantine", u["notify"]))
        for r in all_rules:
            channel = out.setdefault(r.notify, {**self.routing[r.notify], "rules": []})
            channel["rules"].append(r.name)
        return out

    # ---- docs
    def docs_markdown(self) -> str:
        lines = [
            f"# Contract: `{self.dataset}`",
            "",
            f"Generated from `contracts/{self.dataset}.yaml` by `meridian.contracts.compiler`; do not edit by hand.",
            "",
            f"- Owner: `{self.owner}`  ",
            f"- Landing: `/Volumes/<catalog>/landing/raw/{self.landing_path}` ({self.format})  ",
            f"- Freshness: alert when no `{self.event_time_column}` is newer than {self.max_delay_minutes} minutes",
            "",
            "## Reference schema",
            "",
            "| Column | Type | PII |",
            "|---|---|---|",
            *[f"| `{c['name']}` | `{c['type']}` | {c.get('pii', '')} |" for c in self.schema],
            "",
            "## Rules",
            "",
            "| Rule | Expression | Severity | On violation | Notify |",
            "|---|---|---|---|---|",
            *[f"| `{r.name}` | `{r.expr}` | {r.severity} | {r.on_violation} | {r.notify} |" for r in self.rules],
        ]
        if self.uniqueness:
            u = self.uniqueness
            lines.append(f"| `{u['name']}` | unique `{', '.join(u['columns'])}` within {u['watermark']} "
                         f"| {u['severity']} | quarantine (BUILD) | {u['notify']} |")
        if self.pii_handling:
            lines += ["", "## PII handling", "", "| Column | Strategy |", "|---|---|",
                      *[f"| `{k}` | {v} |" for k, v in self.pii_handling.items()]]
        return "\n".join(lines) + "\n"


def validate(raw: dict) -> None:
    for r in raw["rules"]:
        if r["severity"] not in SEVERITIES:
            raise ValueError(f"{r['name']}: severity {r['severity']} not in {SEVERITIES}")
        if r["on_violation"] not in ACTIONS:
            raise ValueError(f"{r['name']}: on_violation {r['on_violation']} not in {ACTIONS}")
        if r["notify"] not in raw["routing"]:
            raise ValueError(f"{r['name']}: notify channel {r['notify']} is not defined in routing")
        if r["on_violation"] == "fail" and r["severity"] != "critical":
            raise ValueError(f"{r['name']}: only critical rules may fail the update")
    names = [r["name"] for r in raw["rules"]]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate rule names in {raw['dataset']}")


def load_contract(path: str | Path) -> Contract:
    raw = yaml.safe_load(Path(path).read_text())
    validate(raw)
    return Contract(
        dataset=raw["dataset"], owner=raw["owner"], landing_path=raw["landing_path"], format=raw["format"],
        max_delay_minutes=raw["max_delay_minutes"], event_time_column=raw["event_time_column"], key=raw["key"],
        schema=raw["schema"], rules=[Rule(**r) for r in raw["rules"]], routing=raw["routing"],
        uniqueness=raw.get("uniqueness"), drift=raw.get("drift"), cdc=raw.get("cdc"),
        pii_handling=raw.get("pii_handling", {}),
    )


def load_all(directory: Path = CONTRACTS_DIR) -> dict[str, Contract]:
    return {c.dataset: c for c in (load_contract(p) for p in sorted(directory.glob("*.yaml")))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate contracts and write their docs pages.")
    parser.add_argument("--docs", type=Path, help="directory for generated markdown")
    args = parser.parse_args()
    contracts = load_all()
    for name, contract in contracts.items():
        print(f"{name}: {len(contract.rules)} rules, routing {sorted(contract.routing_config())}")
        if args.docs:
            args.docs.mkdir(parents=True, exist_ok=True)
            (args.docs / f"{name}.md").write_text(contract.docs_markdown())


if __name__ == "__main__":
    main()
