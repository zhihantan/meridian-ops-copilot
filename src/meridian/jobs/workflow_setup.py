"""Governed workflow objects (T18): apply sql/workflow_objects.sql through a SQL warehouse, seed kb.workflows.

The SQL runs as this job's identity, so the SQL SECURITY DEFINER procedures are owned by the deploying
principal. The membership mirrors the procedures check (agent.approvers, agent.tier_members) are filled by
apply_governance.py as an admin, because this job's principal cannot read group membership (meridian.common.membership).
Workflow versions are seeded from config/workflows/*.yaml with an owner principal and a checksum of their steps;
existing versions are never overwritten, so an approval made in the workspace stands.

    workflow_setup.py --catalog C --bronze-schema S --sql-file F --workflows-dir D --scenario Y --warehouse-id W
                      --principal ava=<app id> --principal ben=<app id>
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import hashlib
import json

import yaml
from databricks.sdk import WorkspaceClient

from meridian.common.sqlfile import statements
from meridian.common.workspace import sql
from meridian.jobs.common import names, parser


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    for flag in ("--sql-file", "--workflows-dir", "--scenario", "--warehouse-id"):
        p.add_argument(flag, required=True)
    p.add_argument("--principal", action="append", default=[], help="persona=principal, for workflow owners")
    args = p.parse_args()
    n = names(args)
    w = WorkspaceClient()
    scenario = yaml.safe_load(Path(args.scenario).read_text())
    values = {"agent": f"{n.catalog}.{n.schema('agent')}", "kb": f"{n.catalog}.{n.schema('kb')}",
              "silver": f"{n.catalog}.{n.schema('silver')}",
              "refund_threshold": str(scenario["policy"]["refund_approval_threshold_sgd"])}
    for statement in statements(args.sql_file, values):
        sql(w, statement, warehouse=args.warehouse_id)
        print("ok:", " ".join(statement.split()[:6]))

    principals = dict(item.split("=", 1) for item in args.principal)
    for path in sorted(Path(args.workflows_dir).glob("*.yaml")):
        wf = yaml.safe_load(path.read_text())
        steps = json.dumps(wf["steps"], sort_keys=True)
        sql(w, f"""MERGE INTO {values['kb']}.workflows t
                   USING (SELECT :workflow_id AS workflow_id, CAST(:version AS INT) AS version) s
                   ON t.workflow_id = s.workflow_id AND t.version = s.version
                   WHEN NOT MATCHED THEN INSERT (workflow_id, version, status, title, owner, approved_by, approved_at,
                     steps, checksum, change_note, loaded_at)
                   VALUES (:workflow_id, CAST(:version AS INT), :status, :title, :owner, :approved_by,
                     IF(:status = 'approved', current_timestamp(), NULL), :steps, :checksum, :change_note,
                     current_timestamp())""",
            warehouse=args.warehouse_id,
            parameters={"workflow_id": wf["workflow_id"], "version": str(wf["version"]), "status": wf["status"],
                        "title": wf["title"], "owner": principals.get(wf["owner"], wf["owner"]),
                        "approved_by": wf.get("approved_by") or "", "steps": steps,
                        "checksum": hashlib.sha256(steps.encode()).hexdigest(),
                        "change_note": (wf.get("change_note") or "").strip()})
        print(f"seeded {wf['workflow_id']} v{wf['version']} ({wf['status']})")
    for r in sql(w, f"SELECT workflow_id, version, status FROM {values['kb']}.workflows ORDER BY 1, 2",
                 warehouse=args.warehouse_id):
        print("  ", r)


if __name__ == "__main__":
    main()
