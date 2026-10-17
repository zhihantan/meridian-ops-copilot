"""The integration test inside the workspace (T09): one step per task of meridian-integration-test, staging only.

prepare        fresh synthetic data anchored to now (meridian.synth.structured), written with its planted.json to
               this run's folder on the exports volume. The landing folders are cleared, then the baseline lands
               (payments/baseline, customers_changes/initial, changes_1, changes_2).
               The job then runs the pipeline from a full refresh.
land_incident  payments/incident, bad_rows and drift land. The job then runs a pipeline update.
score          every planted defect is checked against planted.json (meridian.common.score, the same checks as
               scripts/score_pipeline.py). The scores go to the run's folder, and the task fails on any miss, so
               a change that weakens a contract rule cannot be promoted.

It refuses every target but staging, because it rewrites the landing folders and the pipeline's tables.

    integration.py --catalog C --bronze-schema S --target staging --landing-root /Volumes/... --step prepare
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from meridian.jobs.common import names, parser

BASELINE = ("payments/baseline", "customers_changes/initial", "customers_changes/changes_1",
            "customers_changes/changes_2")
INCIDENT = ("payments/incident", "payments/bad_rows", "payments/drift")
TARGETS = ("staging",)


def land(work: Path, landing: Path, batches: tuple[str, ...]) -> None:
    for batch in batches:
        dest = landing / batch.split("/")[0]
        dest.mkdir(parents=True, exist_ok=True)
        files = sorted((work / batch).glob("*.json"))
        for f in files:
            shutil.copyfile(f, dest / f.name)
        print(f"landed {len(files)} file(s) from {batch} into {dest}")


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--step", required=True, choices=("prepare", "land_incident", "score"))
    p.add_argument("--target", required=True)
    p.add_argument("--landing-root", required=True, help="the pipeline's meridian.landing_root")
    args = p.parse_args()
    if args.target not in TARGETS:
        sys.exit(f"refused on {args.target}: the integration test rewrites the landing folders and pipeline tables")
    n = names(args)
    work = Path(f"/Volumes/{n.catalog}/{n.schema('obs')}/exports/integration/{args.run_id}")
    landing = Path(args.landing_root)

    if args.step == "prepare":
        from meridian.synth.structured import generate, parse_anchor

        planted = generate(parse_anchor("now"), work)
        for dataset in ("payments", "customers_changes"):  # the previous run's files
            if (landing / dataset).exists():
                shutil.rmtree(landing / dataset)
        land(work, landing, BASELINE)
        print(f"anchor {planted['anchor']}; data and planted.json in {work}")
    elif args.step == "land_incident":
        land(work, landing, INCIDENT)
    else:
        from pyspark.sql import SparkSession

        from meridian.common.score import score

        spark = SparkSession.builder.getOrCreate()

        def sql(statement: str) -> list[list]:  # values as strings, as the SQL Statement API returns them
            return [[None if v is None else str(v) for v in row] for row in spark.sql(statement).collect()]

        planted = json.loads((work / "planted.json").read_text())
        results = score(planted, n.table, sql)
        failed = [r for r in results if r["status"] == "FAIL"]
        (work / "score.json").write_text(json.dumps(
            {"target": args.target, "run_id": args.run_id, "scored_at": datetime.now(UTC).isoformat(),
             "anchor": planted["anchor"], "results": results, "status": "FAIL" if failed else "PASS"}, indent=2))
        print(f"{len(results) - len(failed)}/{len(results)} PASS; scores in {work / 'score.json'}")
        if failed:
            sys.exit(f"{len(failed)} planted defect(s) not handled as the contracts say: "
                     + "; ".join(r["check"] for r in failed))


if __name__ == "__main__":
    main()
