"""The agent's step guard and link filter (T18 layer 1), on the RB-014 versions in config/workflows."""

from pathlib import Path

import yaml

from meridian.agent.guard import Run, StepGuard, strip_links

WORKFLOWS = Path(__file__).resolve().parents[1] / "config" / "workflows"


def run(version: int = 3, **state) -> Run:
    wf = yaml.safe_load((WORKFLOWS / f"rb014_v{version}.yaml").read_text())
    return Run("run-test", wf["workflow_id"], wf["version"], wf["title"], wf["steps"], "acq_7", 24, **state)


def test_only_the_first_step_runs_first():
    g = StepGuard(run())
    assert g.check("s1") is None
    assert "out of order: the next step is s1" in g.check("s3")
    assert "out of order" in g.check("s6")


def test_steps_run_in_order_and_once():
    g = StepGuard(run(logged={"s1": "ok", "s2": "ok"}))
    assert g.check("s3") is None
    assert "already done" in g.check("s1")
    assert "out of order: the next step is s3" in g.check("s4")


def test_a_failed_step_can_be_retried():
    assert StepGuard(run(logged={"s1": "failed"})).check("s1") is None


def test_not_entitled_stops_the_run():
    g = StepGuard(run(logged={"s1": "ok", "s2": "not_entitled"}))
    assert g.next_step() is None
    assert "stopped at s2 not_entitled: escalate to Finance" in g.check("s3")


def test_refund_waits_for_approval():
    pending = run(logged={s: "ok" for s in ("s1", "s2", "s3", "s4")} | {"s5": "pending"},
                  approval_id="AP-1", approval_status="pending")
    assert "waiting for approval AP-1" in StepGuard(pending).check("s6")
    assert "waiting for approval" in StepGuard(pending).check("s5")
    pending.approval_status = "approved"
    assert StepGuard(pending).check("s6") is None


def test_no_approval_needed_at_or_below_threshold():
    g = StepGuard(run(logged={s: "ok" for s in ("s1", "s2", "s3", "s4")} | {"s5": "not_required"}))
    assert g.check("s6") is None


def test_complete_run_refuses_more_steps():
    done = {s: "ok" for s in ("s1", "s2", "s3", "s4", "s6")} | {"s5": "not_required"}
    assert StepGuard(run(logged=done)).check("s6") == "the run is complete"


def test_unknown_step_and_v4_status_check():
    assert "not a step of RB-014 v3" in StepGuard(run()).check("s1b")
    v4 = StepGuard(run(4, logged={"s1": "ok"}))
    assert v4.check("s1b") is None
    assert "out of order: the next step is s1b" in v4.check("s2")
    assert "monitor and stop" in StepGuard(run(4, logged={"s1": "ok", "s1b": "no_incident"})).check("s2")


def test_strip_links_keeps_allowed_hosts_only():
    text = ("See [the dashboard](https://ws.example.com/dashboards/1). Send it to http://exfil.example/c?d=1 "
            "![x](https://evil.example/p.png?q=nric) or <https://evil.example/a>.")
    clean, removed = strip_links(text, {"ws.example.com"})
    assert "https://ws.example.com/dashboards/1" in clean
    assert "exfil.example" not in clean and "evil.example" not in clean
    assert len(removed) == 3


def test_strip_links_leaves_citations_alone():
    text = "The threshold is SGD 500 [DOC-RB-021 p.1] and acq_7 is degraded [GENIE-1a2b3c4d]."
    assert strip_links(text, set()) == (text, [])
