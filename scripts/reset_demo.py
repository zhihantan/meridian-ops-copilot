"""Demo reset and readiness (T29): fresh data anchored to now, demo state put back, and the pre-staged scenes.

  reset   regenerate the data and the corpus with a fresh anchor; meridian-demo-reset (as the tables' owner) clears
          the landing folders and rewrites demo state; the baseline lands (payments/baseline, customers_changes/initial),
          then a full refresh rebuilds every pipeline table from it; the corpus lands and kb_sync rebuilds the
          knowledge base; governance is re-applied (PII tags from the contracts, policies, grants, membership
          mirrors); on prod, the personas' memories are cleared (the stores are workspace-wide).
          The incident batch is not landed: it lands live in scene 1. make gen-data also rewrites
          docs/evidence/T02/planted_summary.json for the new anchor.
  stage   what system tables must already hold at demo time (run at least 3 hours before): the bad backfill (T06),
          Claude Code over MCP as each persona (T23) and the caching calls (T27).
  check   readiness: PII masked for Ava, baseline processed and fresh, no incident yet, RB-014 v3 approved and v4
          draft, no workflow runs, empty memories, knowledge synced, copilot running, Genie space present; on prod,
          the live triggers fired after the reset (the baseline landing ran ingest, its write rebuilt gold).
Nothing changes without --yes: the plan is printed instead. Tables are never dropped.

    uv run --group dbx --group agent python scripts/reset_demo.py reset --target prod --yes
    uv run --group dbx --group agent python scripts/reset_demo.py check --target prod
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks_agentkit.client import AgentKitClient

from meridian.common.bundle import target_names
from meridian.common.personas import principal_names
from meridian.common.workspace import sql, warehouse_id

REPO = Path(__file__).resolve().parents[1]
BASELINE = ("payments/baseline", "customers_changes/initial")
APP, GENIE = "agent-bricks-meridian-copilot", "Meridian payments (gold)"
STORES = ("mem-general", "mem-finance")


def run(cmd: list[str], apply: bool) -> None:
    print("+", " ".join(cmd), flush=True)
    if apply:
        subprocess.run(cmd, check=True, cwd=REPO)


def resources(target: str) -> dict:
    out = subprocess.run(["databricks", "bundle", "summary", "-t", target, "-o", "json"], check=True, cwd=REPO,
                         capture_output=True, text=True).stdout
    return json.loads(out)["resources"]


def pipeline_id(target: str) -> str:
    return resources(target)["pipelines"]["dlc"]["id"]


def wait_for_pipeline(w: WorkspaceClient, pid: str, after: datetime, start_grace_s: int = 180,
                      timeout_s: int = 1800) -> str:
    """The newest pipeline update created after `after`, once finished; "none" if none starts within the grace."""
    started = time.time()
    while time.time() - started < timeout_s:
        updates = [u for u in w.pipelines.list_updates(pid).updates or []
                   if u.creation_time and u.creation_time / 1000 > after.timestamp()]
        if not updates and time.time() - started > start_grace_s:
            return "none"
        if updates and updates[0].state and updates[0].state.value in ("COMPLETED", "FAILED", "CANCELED"):
            return updates[0].state.value
        time.sleep(15)
    return "TIMEOUT"


def clear_memories(admin: WorkspaceClient, apply: bool) -> int:
    client, removed = AgentKitClient(admin), 0
    for name in STORES:
        store = client.memory_stores.get(name)
        for principal in principal_names(admin):
            for m in store.list(actor_id=principal):
                removed += 1
                if apply:
                    m.delete()
    print(f"memories: {removed} entr{'y' if removed == 1 else 'ies'} {'deleted' if apply else 'would be deleted'}")
    return removed


def reset(t, admin: WorkspaceClient, apply: bool, anchor: str) -> None:
    run(["make", "gen-data", f"ANCHOR={anchor}"], apply)
    run(["make", "gen-corpus", f"ANCHOR={anchor}"], apply)
    run(["databricks", "bundle", "run", "-t", t.target, "demo_reset_job"], apply)
    # Auto Loader cannot infer a schema from an empty folder, so the baseline lands before the full refresh.
    landed = datetime.now(UTC)
    for batch in BASELINE:
        run(["scripts/land.sh", t.target, batch], apply)
    if apply:  # where triggers are live, landing starts an update; let it finish before the full refresh
        print("update started by landing:", wait_for_pipeline(admin, pipeline_id(t.target), landed))
    refresh = ["databricks", "bundle", "run", "-t", t.target, "dlc", "--full-refresh-all"]
    try:
        run(refresh, apply)
    except subprocess.CalledProcessError:  # an update that started meanwhile: wait for it, then once more
        wait_for_pipeline(admin, pipeline_id(t.target), landed, start_grace_s=0)
        run(refresh, apply)
    # gold.acquirer_status rebuilds on a table-update trigger, which development mode pauses: run it here too.
    run(["databricks", "bundle", "run", "-t", t.target, "gold_refresh_job"], apply)
    # The masks match tags: re-apply the contracts' PII tags (a no-op where present), policies, grants and the
    # membership mirrors, so the rebuilt tables are protected before anyone queries them.
    run(["uv", "run", "--group", "dbx", "python", "scripts/apply_governance.py", "--target", t.target, "--manual-tags"],
        apply)
    run(["scripts/land.sh", t.target, "kb"], apply)
    run(["databricks", "bundle", "run", "-t", t.target, "kb_sync_job", "--params", "full_refresh=true"], apply)
    if t.target == "prod":  # memory stores are workspace-wide and serve the prod copilot
        clear_memories(admin, apply)


def stage(t, apply: bool) -> None:
    run(["databricks", "bundle", "run", "-t", t.target, "bad_backfill_job"], apply)
    run(["uv", "run", "--group", "dbx", "python", "tests/e2e/mcp_personas.py", "--target", t.target], apply)
    run(["uv", "run", "--group", "dbx", "--group", "agent", "python", "scripts/cache_experiment.py", "--calls", "30"],
        apply)


def check(t, admin: WorkspaceClient) -> bool:
    c, s = t.catalog, t.schemas

    def one(query: str) -> str:
        return sql(admin, query)[0][0]

    def ava_masked() -> bool:  # as Ava herself (her CLI profile), on the admin's warehouse
        rows = sql(WorkspaceClient(profile="meridian-ava"), f"""SELECT email, national_id FROM {c}.{s['silver']}.customers
                                                               WHERE email IS NOT NULL LIMIT 1""", warehouse=wh)
        return bool(rows) and "***@" in (rows[0][0] or "") and rows[0][1] is None

    def triggers_fired() -> bool:  # scene 1's chain: the baseline landing ran ingest, and its write rebuilt gold
        jobs = resources(t.target)["jobs"]

        def runs(key: str, **kw):
            return admin.jobs.list_runs(job_id=int(jobs[key]["id"]), **kw)

        reset_run = next(iter(runs("demo_reset_job", limit=1)), None)

        def fired(key: str, trigger: str) -> bool:
            return any(r.trigger and r.trigger.value == trigger and r.state.result_state
                       and r.state.result_state.value in ("SUCCESS", "SUCCESS_WITH_FAILURES")
                       for r in runs(key, start_time_from=reset_run.start_time))
        return reset_run is not None and fired("ingest_job", "FILE_ARRIVAL") and fired("gold_refresh_job", "TABLE")

    wh = warehouse_id(admin)
    checks = {
        "PII masked for Ava (masked email, no NRIC)": ava_masked(),
        "baseline processed (silver.payments has rows)": int(one(f"SELECT count(*) FROM {c}.{s['silver']}.payments")) > 0,
        "data is fresh (the baseline ends within 30 hours; the incident fills the last 24)": one(
            f"SELECT max(created_at) >= current_timestamp() - INTERVAL 30 HOURS FROM {c}.{s['silver']}.payments") == "true",
        "no incident yet (acq_7 not degraded)": one(f"""SELECT coalesce(max(status), 'none') FROM {c}.{s['gold']}.acquirer_status
                                                       WHERE acquirer_id = 'acq_7'""") != "degraded",
        "RB-014 v3 approved, v4 draft": sql(admin, f"""SELECT version, status FROM {c}.{s['kb']}.workflows
                                                      WHERE workflow_id = 'RB-014' ORDER BY version""")
                                        == [["3", "approved"], ["4", "draft"]],
        "no workflow runs or approvals": int(one(f"SELECT count(*) FROM {c}.{s['agent']}.runs")) == 0
                                         and int(one(f"SELECT count(*) FROM {c}.{s['agent']}.approvals")) == 0,
        "knowledge synced (live documents, no failures in the last run)": one(f"""SELECT live_docs_general
            + live_docs_finance > 0 AND failed = 0 FROM {c}.{s['kb']}.sync_status""") == "true",
        "memories empty": t.target != "prod" or clear_memories(admin, apply=False) == 0,
        "live triggers fired after the reset (file arrival ran ingest, the table update rebuilt gold)":
            t.target != "prod" or triggers_fired(),
        "copilot app running": str(admin.apps.get(APP).compute_status.state).endswith("ACTIVE"),
        "Genie space present": any(sp.title == GENIE for sp in admin.genie.list_spaces().spaces or []),
    }
    for name, ok in checks.items():
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    return all(checks.values())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=("reset", "stage", "check"))
    p.add_argument("--target", default="dev")
    p.add_argument("--anchor", default="now", help="the data's time anchor (default: now)")
    p.add_argument("--yes", action="store_true", help="make the changes; without it the plan is printed")
    args = p.parse_args()
    t = target_names(args.target)
    admin = WorkspaceClient()
    if args.action == "check":
        sys.exit(0 if check(t, admin) else 1)
    if not args.yes:
        print(f"plan for {args.action} on {args.target} (nothing changes without --yes):")
    (reset(t, admin, args.yes, args.anchor) if args.action == "reset" else stage(t, args.yes))


if __name__ == "__main__":
    main()
