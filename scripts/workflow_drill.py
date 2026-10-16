"""Governed workflow drill (T18): RB-014 happy path and the attacks the database layer must stop.

Runs the procedures as each persona with their own credentials: Ben (finance) runs RB-014 for acq_7,
Eli (admin) approves, and attacks try to skip, reorder, self-approve, tamper and refund directly. Each
attack must be refused with a reason and leave a row in agent.violations. Agent-level attacks (prompt
injection, exfiltration, another user's memory) are covered by the agent's own drill. Writes
docs/evidence/T18/workflow_drill_<target>.json.

    uv run --group dbx python scripts/workflow_drill.py --target dev
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--approve-v4", action="store_true", help="also approve the RB-014 v4 draft as Eli (not in prod)")
    args = p.parse_args()
    t = target_names(args.target)
    agent = f"{t.catalog}.{t.schemas['agent']}"
    eli, ben, ava = WorkspaceClient(), WorkspaceClient(profile="meridian-ben"), WorkspaceClient(profile="meridian-ava")
    results: dict = {"task": "T18 governed workflow", "target": args.target, "at": datetime.now(UTC).isoformat(),
                     "happy_path": {}, "attacks": {}}

    def call(who: WorkspaceClient, statement: str) -> dict:
        try:
            return {"ok": True, "rows": sql(who, statement)}
        except Exception as exc:  # noqa: BLE001  refusals are the expected outcome of attacks
            text = str(exc).split("\n")[0]
            return {"ok": False, "reason": text.split("SQLSTATE")[0].replace("FAILED: ", "").strip()[:200]}

    def steps(who: WorkspaceClient, run: str, upto: str) -> dict:
        out = {}
        for step in ("s1", "s2"):
            out[step] = call(who, f"CALL {agent}.log_step('{run}', 'RB-014', 3, '{step}', 'ok', 'drill')")
        if upto >= "s3":
            out["s3"] = call(who, f"CALL {agent}.compute_impact('{run}', 'acq_7', 24)")
        if upto >= "s4":
            out["s4"] = call(who, f"CALL {agent}.propose_refund('{run}')")
        return out

    # The workflow the agent may run: v3, not the v4 draft.
    wf = call(ava, f"CALL {agent}.get_workflow('RB-014')")
    results["get_workflow_version"] = wf["rows"][0][1] if wf["ok"] else wf
    results["ben_approves_own_v4"] = call(ben, f"CALL {agent}.approve_workflow('RB-014', 4, 'drill')")

    # Happy path: Ben runs RB-014, Eli approves, Ben executes.
    run = f"drill-{uuid.uuid4().hex[:8]}"
    hp = steps(ben, run, "s4")
    batch_id, total = hp["s4"]["rows"][0][0], hp["s4"]["rows"][0][2]
    hp["s5"] = call(ben, f"CALL {agent}.request_approval('{run}', '{batch_id}')")
    approval = hp["s5"]["rows"][0][1] if hp["s5"]["ok"] else None
    hp["approve_as_eli"] = call(eli, f"CALL {agent}.approve_refund('{approval}', 'drill: impact verified')")
    hp["s6"] = call(ben, f"CALL {agent}.refund_batch('{run}', '{batch_id}', '{approval}')")
    results["happy_path"] = {"run": run, "batch": batch_id, "total_sgd": total, "approval": approval,
                             "steps": {k: v["ok"] for k, v in hp.items()}, "s6": hp["s6"]}

    # Attacks, each on a fresh run.
    def fresh() -> str:
        return f"attack-{uuid.uuid4().hex[:8]}"

    r = fresh()
    steps(ben, r, "s2")  # s3 skipped
    results["attacks"]["skip a step (propose without s3)"] = call(ben, f"CALL {agent}.propose_refund('{r}')")
    r = fresh()
    steps(ben, r, "s3")  # request approval before a batch exists
    results["attacks"]["reorder (approval before s4)"] = call(ben, f"CALL {agent}.request_approval('{r}', 'RB-nonexistent')")
    results["attacks"]["direct refund as Ava, no workflow"] = call(
        ava, f"CALL {agent}.refund_batch('{fresh()}', 'RB-0000000000', NULL)")
    r = fresh()
    s = steps(ben, r, "s4")
    results["attacks"]["over threshold without approval"] = call(
        ben, f"CALL {agent}.refund_batch('{r}', '{s['s4']['rows'][0][0]}', NULL)")
    r = fresh()
    s = steps(eli, r, "s4")
    own = call(eli, f"CALL {agent}.request_approval('{r}', '{s['s4']['rows'][0][0]}')")
    results["attacks"]["requester approves own refund"] = call(
        eli, f"CALL {agent}.approve_refund('{own['rows'][0][1]}', 'self')")
    results["attacks"]["non-admin approves a refund"] = call(
        ben, f"CALL {agent}.approve_refund('{own['rows'][0][1]}', 'not an admin')")
    r = fresh()
    a = steps(ben, r, "s4")
    appr = call(ben, f"CALL {agent}.request_approval('{r}', '{a['s4']['rows'][0][0]}')")
    call(eli, f"CALL {agent}.approve_refund('{appr['rows'][0][1]}', 'drill')")
    r2 = fresh()
    b = steps(ben, r2, "s4")  # a different batch, then reuse the first batch's approval
    results["attacks"]["tampered arguments (another batch's approval)"] = call(
        ben, f"CALL {agent}.refund_batch('{r2}', '{b['s4']['rows'][0][0]}', '{appr['rows'][0][1]}')")
    results["attacks"]["agent logs a step it does not own"] = call(
        ben, f"CALL {agent}.log_step('{fresh()}', 'RB-014', 3, 's4', 'ok', 'fake')")
    results["attacks"]["read the approvals table directly"] = call(ava, f"SELECT * FROM {agent}.approvals")

    if args.approve_v4:
        results["eli_approves_v4"] = call(eli, f"CALL {agent}.approve_workflow('RB-014', 4, 'drill: reviewed s1b')")
        after = call(ava, f"CALL {agent}.get_workflow('RB-014')")
        results["get_workflow_version_after_approval"] = after["rows"][0][1] if after["ok"] else after

    violations = sql(eli, f"SELECT attempted, reason FROM {agent}.violations WHERE at >= current_timestamp() - INTERVAL 1 HOUR")
    results["violations_last_hour"] = len(violations)
    checks = {
        "get_workflow returns v3, not the draft": str(results["get_workflow_version"]) == "3",
        "owner cannot approve own draft": not results["ben_approves_own_v4"]["ok"],
        "happy path executes with an approval": hp["s6"]["ok"] and all(v["ok"] for v in hp.values()),
        "every attack refused": all(not v["ok"] for v in results["attacks"].values()),
        "zero unapproved refunds": len(sql(eli, f"""SELECT 1 FROM {agent}.refund_batches b
            WHERE b.status = 'executed' AND b.total_sgd > 500 AND NOT EXISTS (SELECT 1 FROM {agent}.approvals a
            WHERE a.batch_id = b.batch_id AND a.status = 'approved' AND a.approved_by <> a.requested_by)""")) == 0,
    }
    results["checks"], results["status"] = checks, "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T18" / f"workflow_drill_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str) + "\n")
    for name, outcome in results["attacks"].items():
        print(f"{'refused' if not outcome['ok'] else 'ALLOWED':<8} {name}: {outcome.get('reason', '')}")
    print(results["status"], checks)


if __name__ == "__main__":
    main()
