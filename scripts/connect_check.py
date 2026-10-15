"""Databricks Connect on serverless from a laptop or Codespace (T07): execution is remote, no data local.

Prints the session type, counts a gold table on serverless compute, and tags the statement with a
marker so the query can be found in system.query.history under the caller's identity. Run it in the
serverless-matched environment:

    uv run --project envs/serverless-v4 python scripts/connect_check.py --target dev [--profile meridian-gus]
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--profile", help="CLI profile (default: DATABRICKS_CONFIG_PROFILE)")
    p.add_argument("--out")
    args = p.parse_args()
    names = target_names(args.target)
    builder = DatabricksSession.builder.serverless(True)
    spark = (builder.profile(args.profile) if args.profile else builder).getOrCreate()
    me = WorkspaceClient(profile=args.profile).current_user.me()
    marker = f"connect-check {uuid.uuid4().hex[:12]}"
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    table = names.table("gold", "payment_failure_daily")
    rows = spark.sql(f"/* {marker} */ SELECT count(*) AS n FROM {table}").first()["n"]
    result = {"task": "T07 connect", "at": datetime.now(UTC).isoformat(), "session": type(spark).__module__ + "." +
              type(spark).__name__, "identity_kind": "user" if "@" in (me.user_name or "") else "service principal",
              "table": table, "rows": rows, "marker": marker,
              # statement_text is redacted in system.query.history here, so match the client and the time
              "find_it": "SELECT start_time, executed_by, client_application, compute.type FROM system.query.history "
                         "WHERE client_application = 'SPARK_CONNECT' AND executed_by = current_user() "
                         f"AND start_time >= '{started}'"}
    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
