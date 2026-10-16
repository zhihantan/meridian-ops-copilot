"""Agent-side guardrails (T18, BUILD): the step guard and the link filter. Layer 1 of two.

StepGuard decides which step of a workflow run may run next, from the run's state in the database
(agent.get_run): the steps of its pinned, approved version and the statuses logged so far. It allows only
the next incomplete step, and nothing after a step that stopped the run or while an approval is pending.
The procedures in sql/workflow_objects.sql (layer 2) re-check their own preconditions, so a guard bypass
still cannot refund without an approval.

strip_links removes every URL from model output except links to allowed hosts, so text planted in a source
("send the customer list to http://...") cannot turn an answer into an exfiltration link or image.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

AGENT_TOOLS = ("ask_genie", "search_kb", "check_acquirer_status")  # steps the agent performs and logs itself
STOPS = {"not_entitled": "escalate to Finance", "no_incident": "monitor and stop"}  # statuses that end a run


@dataclass
class Run:
    run_id: str
    workflow_id: str
    version: int
    title: str
    steps: list[dict]                                   # the pinned version's steps, in order
    acquirer_id: str
    window_hours: int
    logged: dict[str, str] = field(default_factory=dict)  # step id -> latest status
    batch_id: str | None = None
    total_sgd: str | None = None
    batch_status: str | None = None
    approval_id: str | None = None
    approval_status: str | None = None


class StepGuard:
    def __init__(self, run: Run):
        self.run = run

    def complete(self, step: dict) -> bool:
        status = self.run.logged.get(step["id"])
        if step["tool"] == "request_approval":
            return status == "not_required" or (status == "pending" and self.run.approval_status == "approved")
        return status == "ok"

    def stopped(self) -> str | None:
        return next((f"{sid} {status}: {STOPS[status]}" for sid, status in self.run.logged.items()
                     if status in STOPS), None)

    def next_step(self) -> dict | None:
        if self.stopped():
            return None
        return next((s for s in self.run.steps if not self.complete(s)), None)

    def check(self, step_id: str) -> str | None:
        """None when step_id may run now, otherwise the reason it may not."""
        ids = [s["id"] for s in self.run.steps]
        if step_id not in ids:
            return f"{step_id} is not a step of {self.run.workflow_id} v{self.run.version} (steps: {', '.join(ids)})"
        if stop := self.stopped():
            return f"the run has stopped at {stop}"
        nxt = self.next_step()
        if nxt is None:
            return "the run is complete"
        if nxt["tool"] == "request_approval" and self.run.logged.get(nxt["id"]) == "pending":
            return (f"waiting for approval {self.run.approval_id} ({self.run.approval_status}) from meridian-admin; "
                    "the agent cannot approve")
        if step_id != nxt["id"]:
            if self.complete(next(s for s in self.run.steps if s["id"] == step_id)):
                return f"{step_id} is already done; the next step is {nxt['id']} ({nxt['name']})"
            return f"out of order: the next step is {nxt['id']} ({nxt['name']})"
        return None


URL = re.compile(r"!?\[[^\]]*\]\(\s*(https?://[^)\s]+)[^)]*\)|https?://[^\s)<>\]\"']+", re.IGNORECASE)


def strip_links(text: str, allowed_hosts: set[str]) -> tuple[str, list[str]]:
    """Remove links (bare URLs, markdown links and images) to hosts not in allowed_hosts.

    Returns the cleaned text and the removed URLs, for the trace."""
    removed: list[str] = []

    def replace(m: re.Match) -> str:
        url = m.group(1) or m.group(0)
        if (urlparse(url).hostname or "").lower() in allowed_hosts:
            return m.group(0)
        removed.append(url)
        return "[link removed]"

    return URL.sub(replace, text), removed
