"""Escalation for failed quality checks (T05, T06, BUILD): post this run's breaches to Slack.

Runs only when an upstream check task fails (run_if: AT_LEAST_ONE_FAILED). Without the Slack secret
it writes the message to the job log, and the job's native failure email still fires.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from pyspark.sql import SparkSession

from meridian.jobs.common import names, parser, post_slack, read_uc_secret

SOURCES = [("obs", "drift_events"), ("obs", "freshness_events"), ("gov", "pii_coverage")]


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--slack-secret", required=True, help="catalog.schema.name of the bot token")
    p.add_argument("--channel", default="#meridian-dq-alerts")
    args = p.parse_args()
    n = names(args)
    spark = SparkSession.builder.getOrCreate()

    lines = []
    for layer, name in SOURCES:
        table = n.table(layer, name)
        if not spark.catalog.tableExists(table):
            continue
        for r in spark.sql(f"SELECT check_name, message FROM {table} WHERE run_id = '{args.run_id}' "
                           "AND breached ORDER BY check_name").collect():
            lines.append(f"• [{r['check_name']}] {r['message']}")
    if not lines:
        lines = ["• a quality-check task failed without writing a breach; see the job run for the error"]
    text = f":rotating_light: Meridian data quality: {len(lines)} issue(s) in run {args.run_id} ({n.catalog})\n" \
           + "\n".join(lines)
    post_slack(read_uc_secret(args.slack_secret), args.channel, text)


if __name__ == "__main__":
    main()
