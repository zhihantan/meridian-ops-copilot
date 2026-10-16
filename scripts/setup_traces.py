"""Copilot traces in Unity Catalog (T17, T19, T27): an MLflow experiment linked to <catalog>.agent tables.

Spans are written as OpenTelemetry records straight into Delta tables (<prefix>_otel_spans and friends), not
through artifact uploads, which the app cannot reach here. The app's service principal can write them;
meridian-admin can read them. Traces hold questions, retrieved passages and answers, finance ones included, so no
other group gets access. Then bind it: `agentbricks tracing bind --experiment-name <name> --source apps/copilot`.

    uv run --group dbx --group agent python scripts/setup_traces.py --target prod --app agent-bricks-meridian-copilot
"""

from __future__ import annotations

import argparse
import os

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.entities.trace_location import UnityCatalog

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

EXPERIMENT = "/Shared/agentbricks_traces/meridian-copilot-uc"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    p.add_argument("--app", default="agent-bricks-meridian-copilot")
    p.add_argument("--prefix", default="copilot")
    args = p.parse_args()
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    t = target_names(args.target)
    schema = t.schemas["agent"]
    mlflow.set_tracking_uri("databricks")
    exp = mlflow.set_experiment(EXPERIMENT, trace_location=UnityCatalog(t.catalog, schema, args.prefix))
    print(f"experiment {EXPERIMENT} ({exp.experiment_id}) -> {t.catalog}.{schema}.{args.prefix}_otel_*")
    w = WorkspaceClient()
    app_sp = w.apps.get(args.app).service_principal_client_id
    objects = sql(w, f"""SELECT table_name, table_type FROM {t.catalog}.information_schema.tables
                         WHERE table_schema = '{schema}' AND table_name LIKE '{args.prefix}\\_%'""")
    tables = [name for name, _ in objects]
    for name, kind in objects:
        writes = "" if "VIEW" in kind else ", MODIFY"  # views take SELECT only
        sql(w, f"GRANT SELECT{writes} ON TABLE {t.catalog}.{schema}.{name} TO `{app_sp}`")
        sql(w, f"GRANT SELECT ON TABLE {t.catalog}.{schema}.{name} TO `meridian-admin`")
    sql(w, f"GRANT USE CATALOG ON CATALOG {t.catalog} TO `{app_sp}`")
    sql(w, f"GRANT USE SCHEMA ON SCHEMA {t.catalog}.{schema} TO `{app_sp}`")
    print(f"app principal can write {len(tables)} trace table(s): {', '.join(tables)}; meridian-admin can read them")


if __name__ == "__main__":
    main()
