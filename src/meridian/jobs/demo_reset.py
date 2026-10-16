"""Demo reset, the part that needs the tables' owner (T29): landing cleared and demo state rewritten. No DROP.

Run by meridian-demo-reset as this target's job identity, which owns the pipeline, knowledge and workflow tables:
1. landing: every file under raw/payments, raw/customers_changes and raw/kb is removed (re-landed from the
   generator by scripts/reset_demo.py);
2. RB-014: v3 approved, v4 a draft again (rows of kb.workflows rewritten);
3. workflow runs: agent.runs, step_log, impacts, refund_batches, approvals and violations emptied with DELETE;
4. corrections: approved ones marked reverted, so the next kb_sync stops serving them.
kb.audit_log is never cleared: the reset itself is written to it.

    demo_reset.py --catalog C --bronze-schema S --landing-root /Volumes/<catalog>/<landing>/raw
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import shutil

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser

LANDING = ("payments", "customers_changes", "kb")
RUN_TABLES = ("runs", "step_log", "impacts", "refund_batches", "approvals", "violations")


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--landing-root", required=True)
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    kb, agent = f"{n.catalog}.{n.schema('kb')}", f"{n.catalog}.{n.schema('agent')}"
    done = []

    for folder in LANDING:
        path = Path(args.landing_root) / folder
        if path.exists():
            files = sum(1 for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path)
            done.append(f"landing {folder}: {files} file(s) removed")

    if spark.catalog.tableExists(f"{kb}.workflows"):
        spark.sql(f"""UPDATE {kb}.workflows SET status = CASE version WHEN 3 THEN 'approved' ELSE 'draft' END,
                        approved_by = CASE version WHEN 3 THEN approved_by END,
                        approved_at = CASE version WHEN 3 THEN approved_at END
                      WHERE workflow_id = 'RB-014'""")
        done.append("RB-014: v3 approved, v4 draft")
    for table in RUN_TABLES:
        if spark.catalog.tableExists(f"{agent}.{table}"):
            deleted = spark.sql(f"DELETE FROM {agent}.{table}").first()["num_affected_rows"]
            done.append(f"{agent}.{table}: {deleted} row(s) deleted")
    if spark.catalog.tableExists(f"{kb}.corrections"):
        reverted = spark.sql(f"""UPDATE {kb}.corrections SET status = 'reverted', decided_by = current_user(),
                                   decided_at = current_timestamp(), decision_reason = 'demo reset'
                                 WHERE status = 'approved'""").first()["num_affected_rows"]
        done.append(f"corrections: {reverted} approved one(s) reverted")
    if spark.catalog.tableExists(f"{kb}.audit_log"):
        spark.sql(f"""INSERT INTO {kb}.audit_log VALUES (current_timestamp(), current_user(), 'demo_reset', :target,
                        'demo reset before a rehearsal or the demo', :details)""",
                  args={"target": n.catalog, "details": "; ".join(done)})
    for line in done:
        print(line)


if __name__ == "__main__":
    main()
