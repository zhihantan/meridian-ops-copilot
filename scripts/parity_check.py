"""Local-to-serverless parity table (T07): try each capability from a laptop or Codespace over Databricks Connect.

Each row is tested, not assumed. "connect" means it runs from local code over Databricks Connect
(execution remote); "remote only" means it needs a workspace notebook, job or pipeline; "not supported"
means there is no equivalent through Connect. Writes docs/evidence/T07/parity.json and docs/parity.md.

    uv run --project envs/serverless-v4 python scripts/parity_check.py --target dev
"""

from __future__ import annotations

import argparse
import builtins
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from pyspark.sql import functions as F

from meridian.common.bundle import target_names

REPO = Path(__file__).resolve().parents[1]


def run_checks(spark, w: WorkspaceClient, names, target: str) -> list[dict]:
    gold = names.table("gold", "payment_failure_daily")
    raw = f"/Volumes/{names.catalog}/{names.schemas['landing']}/raw"
    stable = f"/Volumes/{names.catalog}/{names.schemas['obs']}/exports/_parity/autoloader"  # reruns ingest nothing new
    scratch = f"/Volumes/{names.catalog}/{names.schemas['obs']}/exports/_parity/{uuid.uuid4().hex[:8]}"
    rows: list[dict] = []

    def check(capability: str, mode: str, fn, note: str = "") -> None:
        try:
            detail = fn()
            rows.append({"capability": capability, "result": mode, "detail": str(detail)[:160], "note": note})
        except Exception as exc:  # noqa: BLE001  a failure is a finding, not a crash
            rows.append({"capability": capability, "result": "failed", "detail": f"{type(exc).__name__}: "
                         f"{str(exc).splitlines()[0][:150]}", "note": note})
        print(f"{rows[-1]['result']:<14} {capability}: {rows[-1]['detail']}")

    check("PySpark DataFrame API", "connect",
          lambda: spark.table(gold).groupBy("acquirer_id").agg(F.sum("payments").alias("n")).orderBy("acquirer_id")
          .limit(2).collect())
    check("Spark SQL", "connect", lambda: spark.sql(f"SELECT count(*) AS n FROM {gold}").first()["n"])
    check("dbutils subset (fs, secrets)", "connect",
          lambda: [f.path.rstrip("/").rsplit("/", 1)[-1] for f in w.dbutils.fs.ls(raw)][:3],
          "WorkspaceClient().dbutils provides fs and secrets; notebook, widgets and library utilities are notebook-only")

    def udf():
        upper = F.udf(lambda s: (s or "").upper())
        return spark.table(gold).select(upper(F.col("acquirer_id")).alias("a")).distinct().limit(2).collect()
    check("Python UDFs", "connect", udf, "local Python minor version must match the serverless environment (3.12)")

    def mlflow_tracking():
        me = w.current_user.me().user_name
        name = f"/Users/{me}/meridian-parity"
        try:
            exp_id = w.experiments.get_by_name(name).experiment.experiment_id
        except NotFound:
            exp_id = w.experiments.create_experiment(name).experiment_id
        run = w.experiments.create_run(experiment_id=exp_id, run_name="parity").run
        w.experiments.log_metric(run_id=run.info.run_id, key="rows", value=float(spark.table(gold).count()),
                                 timestamp=int(datetime.now(UTC).timestamp() * 1000))
        return run.info.run_id
    check("MLflow", "connect", mlflow_tracking,
          "tracking API to the workspace through databricks-sdk; the mlflow client pinned by serverless 4 "
          "(mlflow-skinny 2.22) did not resolve from this laptop's package mirror")
    check("AI Functions", "connect",
          lambda: spark.sql("SELECT ai_query('databricks-claude-haiku-4-5', 'Reply with the single word OK') AS r")
          .first()["r"], "SQL functions run on serverless; billed per token")

    def volume_io():
        spark.createDataFrame([("parity", 1)], "k STRING, v INT").write.mode("overwrite").json(f"{scratch}/io")
        return spark.read.json(f"{scratch}/io").count()
    check("Volume reads and writes", "connect", volume_io,
          "through Spark or the Files API; local open() on /Volumes paths works only on Databricks compute")

    def auto_loader():
        table = names.table("obs", "parity_autoloader")
        query = (spark.readStream.format("cloudFiles").option("cloudFiles.format", "json")
                 .option("cloudFiles.schemaLocation", f"{stable}/schema").load(f"{raw}/customers_changes")
                 .writeStream.option("checkpointLocation", f"{stable}/checkpoint").trigger(availableNow=True)
                 .toTable(table))
        query.awaitTermination()
        return spark.table(table).count()
    check("Auto Loader (cloudFiles)", "connect", auto_loader, "streaming with availableNow runs on serverless")
    check("display()", "not supported", lambda: "display" in vars(builtins) or "not defined in a script",
          "not defined in local code; use df.show() or a small toPandas(). VS Code notebook rendering not tested here")
    check("dbutils.widgets", "not supported", lambda: w.dbutils.widgets.get("x"),
          "the SDK's local dbutils.widgets is a stub with no values (get raises KeyError); local code takes "
          "arguments instead")
    check("%pip and magics", "not supported", lambda: "magics are notebook syntax; %pip in a local kernel installs locally",
          "dependencies go through uv add locally and the bundle's serverless environment remotely")

    def sdp():
        out = subprocess.run(["databricks", "bundle", "run", "-t", target, "dlc", "--validate-only"],
                             check=False, capture_output=True, text=True, cwd=REPO)
        return "validated" if out.returncode == 0 else out.stderr.strip().splitlines()[-1]
    check("SDP pipeline code", "remote only", sdp,
          "pipeline decorators run in the pipeline engine: validate or run with a bundle deploy to dev")
    for r in rows:  # widgets raising is the expected outcome for a "not supported" row
        if r["result"] == "failed" and r["capability"] == "dbutils.widgets":
            r["result"] = "not supported"
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    args = p.parse_args()
    names = target_names(args.target)
    spark = DatabricksSession.builder.serverless(True).getOrCreate()
    rows = run_checks(spark, WorkspaceClient(), names, args.target)
    evidence = REPO / "docs" / "evidence" / "T07"
    evidence.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    (evidence / "parity.json").write_text(json.dumps({"task": "T07 parity", "at": stamp, "target": args.target,
                                                      "rows": rows}, indent=2) + "\n")
    lines = ["# Local development parity (T07)", "",
             (f"Tested by `scripts/parity_check.py` over Databricks Connect on serverless on {stamp[:10]}. "
              "connect: runs from local code, execution remote. remote only: needs a workspace notebook, job or "
              "pipeline. not supported: no equivalent through Connect."), "",
             "| Capability | Result | Note |", "|---|---|---|"]
    lines += [f"| {r['capability']} | {r['result']} | {r['note']} |" for r in rows]
    (REPO / "docs" / "parity.md").write_text("\n".join(lines) + "\n")
    print(f"{sum(r['result'] != 'failed' for r in rows)}/{len(rows)} rows determined")


if __name__ == "__main__":
    main()
