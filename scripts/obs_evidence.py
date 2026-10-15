"""Evidence for centralized logs and the lineage changelog (T06b). Read-only.

Collects: the latest lineage changes (gov.lineage_changelog, excluding the baseline), the answer to
"what failed in the last 24h and why" (obs.v_pipeline_health), and the dated files of the log export.

    uv run --group dbx python scripts/obs_evidence.py --target prod [--out docs/evidence/T06b/obs_prod.json]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

FAILED = ("FAILED", "ERROR", "BREACH", "QUARANTINED", "INTERNAL_ERROR", "TIMED_OUT")


def person_free(identity: str | None) -> str | None:
    """Evidence is public: keep service principal IDs, replace user emails."""
    return "<user>" if identity and "@" in identity else identity


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--out")
    args = p.parse_args()
    w = WorkspaceClient()
    t = target_names(args.target)
    result: dict = {"task": "T06b", "target": args.target, "collected_at": datetime.now(UTC).isoformat()}

    changes = sql(w, f"""SELECT detected_at, change, source, target, entity_type, entity_name, created_by, first_seen
                         FROM {t.table('gov', 'lineage_changelog')} WHERE change <> 'baseline'
                         ORDER BY detected_at DESC, source LIMIT 30""")
    result["lineage_changes"] = [dict(zip(("detected_at", "change", "source", "target", "entity_type", "entity",
                                           "created_by", "first_seen"), [*r[:6], person_free(r[6]), r[7]]))
                                 for r in changes]
    result["lineage_snapshots"] = sql(w, f"""SELECT snapshot_id, count(*) FROM {t.table('gov', 'lineage_snapshot')}
                                             GROUP BY snapshot_id ORDER BY snapshot_id""")

    listed = ", ".join(f"'{s}'" for s in FAILED)
    result["what_failed_24h"] = [dict(zip(("at", "source", "name", "run_id", "status", "detail"), r)) for r in sql(w, f"""
        SELECT at, source, name, run_id, status, left(detail, 160) FROM {t.table('obs', 'v_pipeline_health')}
        WHERE status IN ({listed}) ORDER BY at DESC LIMIT 25""")]
    result["health_by_source"] = sql(w, f"""SELECT source, status, count(*) FROM {t.table('obs', 'v_pipeline_health')}
                                            GROUP BY ALL ORDER BY 1, 2""")

    root = f"/Volumes/{t.catalog}/{t.schemas['obs']}/exports/logs"
    result["log_export"] = {d.name: sorted(f.name for f in w.files.list_directory_contents(d.path))
                            for d in w.files.list_directory_contents(root) if d.is_directory}
    result["checks"] = {"lineage change detected": any(c["change"] == "added" for c in result["lineage_changes"]),
                        "health view answers what failed": bool(result["what_failed_24h"]),
                        "dated log export exists": any("manifest.json" in v for v in result["log_export"].values())}
    result["status"] = "PASS" if all(result["checks"].values()) else "OPEN"
    text = json.dumps(result, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
