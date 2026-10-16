"""Workflow tools (T18, BUILD): runbook runs the agent drives one step at a time, as the caller.

start_workflow starts a run of the latest approved version (agent.start_run pins it). run_step runs a step only
if StepGuard (meridian.agent.guard) allows it, and every argument a step needs (acquirer, window, batch,
approval) comes from the run's state in the database, never from the model. Data, knowledge and status steps
are performed here and logged with agent.log_step; impact, batch, approval request and refund are SQL SECURITY
DEFINER procedures that re-check their own preconditions. Nothing here can approve: a member of meridian-admin
approves in SQL with agent.approve_refund.
"""

from __future__ import annotations

import json
import os
import re

import mlflow
from mlflow.entities import SpanType

from meridian.agent.guard import AGENT_TOOLS, STOPS, Run, StepGuard
from meridian.common.workspace import sql, warehouse_id

DEFINITIONS = [
    {"name": "start_workflow",
     "description": "Start a run of an approved runbook workflow, such as RB-014 (acquirer degradation response), "
                    "for one acquirer and a window in hours. Returns the run id, the version that runs and its steps.",
     "input_schema": {"type": "object", "properties": {
         "workflow_id": {"type": "string"}, "acquirer_id": {"type": "string"}, "window_hours": {"type": "integer"}},
         "required": ["workflow_id", "acquirer_id", "window_hours"]}},
    {"name": "run_step",
     "description": "Run one step of a workflow run. Steps run strictly in order and anything else is refused with "
                    "the reason. Amounts, batches and approvals come from the run itself, not from arguments.",
     "input_schema": {"type": "object", "properties": {"run_id": {"type": "string"}, "step_id": {"type": "string"}},
                      "required": ["run_id", "step_id"]}},
]


def refusal(exc: Exception) -> str:
    """The reason a procedure gave (its SIGNAL message), without the SQL state and statement."""
    first = str(exc).split("\n")[0].replace("FAILED: ", "").split("SQLSTATE")[0]
    return re.sub(r"^\[[A-Z_.]+\]\s*", "", first).strip()[:300]


class Workflows:
    def __init__(self, tools):  # copilot.tools.Tools: the caller, their retriever and Genie
        self.tools = tools
        self.agent = os.environ.get("MERIDIAN_AGENT_SCHEMA", "meridian.agent")
        self.gold = os.environ.get("MERIDIAN_GOLD_SCHEMA", "meridian.gold")
        self._warehouse: str | None = None

    def sql(self, statement: str, **params) -> list[list]:
        client = self.tools.caller.client
        self._warehouse = self._warehouse or warehouse_id(client)
        return sql(client, statement, warehouse=self._warehouse,
                   parameters={k: str(v) for k, v in params.items()} or None)

    def start(self, workflow_id: str, acquirer_id: str, window_hours: int) -> dict:
        with mlflow.start_span(name="start_workflow", span_type=SpanType.TOOL) as span:
            span.set_inputs({"workflow_id": workflow_id, "acquirer_id": acquirer_id, "window_hours": window_hours})
            try:
                run_id, wf, version, title, steps = self.sql(
                    f"CALL {self.agent}.start_run(:workflow_id, :acquirer_id, CAST(:window_hours AS INT))",
                    workflow_id=workflow_id, acquirer_id=acquirer_id, window_hours=int(window_hours))[0]
                steps = json.loads(steps)
                out = {"run_id": run_id, "workflow": f"{wf} v{version}", "title": title,
                       "acquirer_id": acquirer_id, "window_hours": int(window_hours),
                       "steps": [{"id": s["id"], "name": s["name"], "description": " ".join(s["description"].split())}
                                 for s in steps],
                       "next_step": steps[0]["id"]}
            except (TypeError, ValueError, RuntimeError) as exc:
                out = {"refused": refusal(exc)}
            span.set_outputs(out)
        return out

    def load(self, run_id: str) -> Run | None:
        rows = self.sql(f"CALL {self.agent}.get_run(:run_id)", run_id=run_id)  # the caller's own runs only
        if not rows:
            return None
        r = rows[0]
        logged = {e["step_id"]: e["status"] for e in sorted(json.loads(r[7] or "[]"), key=lambda e: e["at"])}
        return Run(r[0], r[1], int(r[2]), r[3], json.loads(r[4]), r[5], int(r[6]), logged, r[8], r[9], r[10],
                   r[11], r[12])

    def refuse(self, run_id: str, step_id: str, reason: str) -> dict:
        try:
            self.sql(f"CALL {self.agent}.log_violation(:run_id, :attempted, :reason)", run_id=run_id,
                     attempted=f"run_step {step_id}", reason=reason)
        except RuntimeError:
            pass  # the refusal stands whether or not it could be recorded
        return {"run_id": run_id, "step": step_id, "refused": reason}

    def step(self, run_id: str, step_id: str) -> dict:
        with mlflow.start_span(name="run_step", span_type=SpanType.TOOL) as span:
            span.set_inputs({"run_id": run_id, "step_id": step_id})
            out = self._step(run_id, step_id)
            span.set_attribute("refused", "refused" in out)
            span.set_outputs(out)
        return out

    def _step(self, run_id: str, step_id: str) -> dict:
        try:
            run = self.load(run_id)
        except RuntimeError as exc:
            return {"run_id": run_id, "step": step_id, "error": refusal(exc)}
        if run is None:
            return self.refuse(run_id, step_id, f"no run {run_id} started by you")
        if reason := StepGuard(run).check(step_id):
            return self.refuse(run_id, step_id, reason)
        step = next(s for s in run.steps if s["id"] == step_id)
        try:
            out = {"run_id": run_id, "step": step_id, "name": step["name"], **self.perform(run, step)}
        except RuntimeError as exc:  # a procedure refused, and logged its own violation
            return {"run_id": run_id, "step": step_id, "refused": refusal(exc)}
        run.logged[step_id] = out["status"]
        guard = StepGuard(run)
        nxt = guard.next_step()
        waiting = guard.check(nxt["id"]) if nxt else None
        out["next_step"] = None if nxt is None or waiting else nxt["id"]
        if waiting:
            out["waiting"] = waiting
        if stop := guard.stopped():
            out["stopped"] = stop
        return out

    def log(self, run: Run, step: dict, status: str, detail: str) -> None:
        self.sql(f"CALL {self.agent}.log_step(:run_id, :step_id, :status, :detail)", run_id=run.run_id,
                 step_id=step["id"], status=status, detail=detail[:500])

    def perform(self, run: Run, step: dict) -> dict:
        tool, acq, hours = step["tool"], run.acquirer_id, run.window_hours
        if tool in AGENT_TOOLS:
            out = getattr(self, tool)(run, step)
            self.log(run, step, out["status"], out.pop("detail"))
            return out
        if tool == "compute_impact":
            payments, total = self.sql(f"CALL {self.agent}.compute_impact(:run_id)", run_id=run.run_id)[0]
            return {"status": "ok", "acquirer_id": acq, "window_hours": hours, "payments": payments,
                    "total_sgd": total}
        if tool == "propose_refund":
            batch, payments, total = self.sql(f"CALL {self.agent}.propose_refund(:run_id)", run_id=run.run_id)[0]
            run.batch_id = batch
            return {"status": "ok", "batch_id": batch, "payments": payments, "total_sgd": total}
        if tool == "request_approval":
            status, approval, total = self.sql(f"CALL {self.agent}.request_approval(:run_id, :batch_id)",
                                               run_id=run.run_id, batch_id=run.batch_id or "")[0]
            run.approval_id, run.approval_status = approval, "pending" if approval else None
            out = {"status": "pending" if status == "pending_approval" else status, "approval_id": approval,
                   "total_sgd": total}
            if approval:
                out["note"] = (f"Waiting for a member of meridian-admin other than you to approve {approval}. "
                               "The agent cannot approve.")
            return out
        if tool == "refund_batch":
            approval = run.approval_id if run.approval_status == "approved" else None
            statement = (f"CALL {self.agent}.refund_batch(:run_id, :batch_id, :approval_id)" if approval else
                         f"CALL {self.agent}.refund_batch(:run_id, :batch_id, CAST(NULL AS STRING))")
            params = {"run_id": run.run_id, "batch_id": run.batch_id or ""}
            batch, total, status = self.sql(statement, **params, **({"approval_id": approval} if approval else {}))[0]
            return {"status": "ok", "batch_id": batch, "total_sgd": total, "batch_status": status,
                    "approval_id": approval}
        return {"status": "failed", "error": f"step tool {tool} is not available to the agent"}

    # Steps the agent performs itself. Each returns a status for log_step and a short detail.

    def ask_genie(self, run: Run, step: dict) -> dict:
        res = self.tools.ask_genie(  # the wording of a curated example in config/genie_space.yaml
            f"For {run.acquirer_id} in the last {run.window_hours} hours, what is its failure rate compared with its "
            "14-day baseline, and how many failed payments had refundable failure codes, with their SGD value?")
        labels = [q["source"] for q in res.get("queries", []) if q.get("rows")]
        return {"status": "ok" if labels else "failed", "detail": " ".join(labels) or res.get("error", "no rows"),
                **res}

    def check_acquirer_status(self, run: Run, step: dict) -> dict:
        rows = self.sql(f"SELECT status, recent_failure_rate, baseline_failure_rate FROM {self.gold}.acquirer_status "
                        "WHERE acquirer_id = :acquirer_id", acquirer_id=run.acquirer_id)
        status = rows[0][0] if rows else "unknown"
        out = {"status": "ok" if status == "degraded" else "no_incident", "acquirer_status": status,
               "detail": f"acquirer_status {status}"}
        if rows:
            out |= {"recent_failure_rate": rows[0][1], "baseline_failure_rate": rows[0][2]}
        return out

    def search_kb(self, run: Run, step: dict) -> dict:
        tier = step.get("tier")
        if tier and tier not in self.tools.tiers:  # decided from the caller's groups, not by the model
            return {"status": "not_entitled", "detail": f"caller is not entitled to the {tier} tier",
                    "stop": f"This step reads {tier}-tier knowledge you are not entitled to: "
                            f"{STOPS['not_entitled']}."}
        res = self.tools.search_kb(f"{run.acquirer_id} service-level agreement: breach, service credit, claim",
                                   only=[tier] if tier else None)
        if tier in self.tools.retriever.refused:  # Unity Catalog refused the index: not entitled after all
            return {"status": "not_entitled", "detail": f"the {tier} index refused the caller",
                    "stop": f"The {tier} index refused you: {STOPS['not_entitled']}."}
        labels = [r["source"] for r in res["results"]]
        return {"status": "ok" if labels else "failed", "detail": " ".join(labels) or "no relevant passage", **res}
