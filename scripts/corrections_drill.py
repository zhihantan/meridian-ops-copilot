"""Feedback and corrections drill (T20): knowledge gaps, feedback, corrections, a person's decision, re-run, revert.

Runs on a bundle target's knowledge base (dev by default), with each persona's own credentials, through the
retriever and answer step the copilot uses. For each question in config/feedback_questions.yaml: ask (the
baseline, expected to fail), give feedback (down) and propose the correction. Eli (meridian-admin) approves two,
rejects one and leaves one proposed; kb_sync indexes the approved ones. Ask again: the approved two must improve,
the other two must not be served. The golden set's test split runs before and after with T16's code checks
(abstained when it should, cited an expected document, stated the key fact), to catch regressions. Then one
approved correction is reverted and synced: it must stop being served. Attacks: Ava proposes a finance
correction, Ava approves one, Eli approves his own, a rejected correction is approved.
Writes docs/evidence/T20/corrections_<target>.json.

    uv run --group dbx --group agent python scripts/corrections_drill.py --target dev
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from meridian.agent.answer import CONFIG, answer, gateway_client
from meridian.common.bundle import target_names
from meridian.common.personas import principal_names, scrub
from meridian.common.workspace import sql
from meridian.kb.retrieve import Retriever

REPO = Path(__file__).resolve().parents[1]
PROFILES = {"ava": "meridian-ava", "ben": "meridian-ben"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    args = p.parse_args()
    t = target_names(args.target)
    kb = f"{t.catalog}.{t.schemas['kb']}"
    people = {name: WorkspaceClient(profile=prof) for name, prof in PROFILES.items()} | {"eli": WorkspaceClient()}
    retrievers = {name: Retriever(w, kb) for name, w in people.items()}
    model = gateway_client(people["eli"])
    spec = yaml.safe_load((REPO / "config" / "feedback_questions.yaml").read_text())["questions"]
    golden = [q for q in yaml.safe_load((REPO / "config" / "golden_qa.yaml").read_text())["questions"]
              if q["split"] == "test"]
    result: dict = {"task": "T20 feedback and corrections", "target": args.target,
                    "at": datetime.now(UTC).isoformat(), "attacks": {}}
    started = sql(people["eli"], "SELECT current_timestamp()")[0][0]  # the warehouse's clock and time zone

    def call(who: str, statement: str, **params) -> dict:
        try:
            return {"ok": True, "rows": sql(people[who], statement, parameters={k: str(v) for k, v in params.items()})}
        except RuntimeError as exc:
            return {"ok": False, "reason": str(exc).split("\n")[0].split("SQLSTATE")[0].replace("FAILED: ", "")[:200]}

    def ask(who: str, question: str) -> dict:
        hits = retrievers[who].search(question, CONFIG["retrieval_variant"], CONFIG["top_k"])
        a = answer(model, question, hits)
        return {"answer": a["answer"], "abstained": a["abstained"], "cited": sorted({d for d, _ in a["citations"]})}

    def scored(q: dict, a: dict) -> dict:
        return a | {"key_fact_stated": q["key_fact"].lower() in a["answer"].lower(),
                    "cites_correction": any(d.startswith("CORR-") for d in a["cited"])}

    def golden_checks() -> dict:
        out = {}
        for q in golden:
            a = ask("ben" if q["tier_required"] == "finance" else "ava", q["question"])
            out[q["id"]] = {"abstention_ok": a["abstained"] == (not q["answerable"]),
                            "cites_expected": None if not q["answerable"] else
                            any(d in a["cited"] for d in q["expected_doc_ids"]),
                            "key_fact": None if not q["answerable"] else q["key_fact"].lower() in a["answer"].lower()}
        return out

    def kb_sync() -> float:
        started = time.time()
        subprocess.run(["databricks", "bundle", "run", "-t", args.target, "kb_sync_job"], check=True,
                       capture_output=True, text=True, cwd=REPO)
        return round(time.time() - started, 1)

    def wait_for(who: str, query: str, doc_id: str, present: bool, timeout_s: int = 900) -> float | None:
        started = time.time()
        while time.time() - started < timeout_s:
            hits = retrievers[who].search(query, "V1", 10)
            if any(h.doc_id == doc_id for h in hits) == present:
                return round(time.time() - started, 1)
            time.sleep(15)
        return None

    # 0. A previous run's approved corrections would answer the gaps: revert them first, the governed way.
    by_title = {q["correction"]["title"]: q for q in spec}
    leftovers = [(cid, by_title[title]) for cid, title in sql(people["eli"], f"""SELECT correction_id, title
        FROM {kb}.corrections WHERE status = 'approved'""") if title in by_title]
    for cid, _ in leftovers:
        call("eli", f"CALL {kb}.revert_correction(:c, 'drill: reset before a re-run')", c=cid)
    if leftovers:
        kb_sync()
        result["reset"] = {cid: wait_for(q["persona"], q["question"], cid, False) for cid, q in leftovers}

    # 1. Baseline: every gap fails today, and the test split as it stands.
    rows = {q["id"]: {"question": q["question"], "persona": q["persona"], "tier": q["tier"],
                      "decision": q["decision"], "baseline": scored(q, ask(q["persona"], q["question"]))}
            for q in spec}
    result["golden_test_before"] = golden_checks()

    # 2. Feedback and proposed corrections, as the person who asked.
    for q in spec:
        r = rows[q["id"]]
        fb = call(q["persona"], f"CALL {kb}.submit_feedback(:q, :a, 'down', :c, NULL)", q=q["question"],
                  a=r["baseline"]["answer"], c="the knowledge base does not have this")
        r["feedback_id"] = fb["rows"][0][0] if fb["ok"] else fb
        c = call(q["persona"], f"CALL {kb}.submit_correction(:tier, :title, :text, NULL, :reason, :fb)",
                 tier=q["tier"], title=q["correction"]["title"], text=" ".join(q["correction"]["text"].split()),
                 reason=f"feedback {r['feedback_id']}", fb=r["feedback_id"])
        r["correction_id"] = c["rows"][0][0] if c["ok"] else None
        r["submitted"] = c

    # 3. Attacks on the decision path.
    attacks = result["attacks"]
    attacks["Ava proposes a finance correction"] = call(
        "ava", f"CALL {kb}.submit_correction('finance', 'Fee override', 'acq_2 charges nothing.', NULL, 'drill', NULL)")
    first = rows[spec[0]["id"]]["correction_id"]
    attacks["Ava (not an admin) approves a correction"] = call("ava", f"CALL {kb}.approve_correction(:c, 'drill')", c=first)
    own = call("eli", f"CALL {kb}.submit_correction('general', 'Drill: self approval', 'Not served.', NULL, 'drill', NULL)")
    if own["ok"]:
        attacks["Eli approves his own correction"] = call("eli", f"CALL {kb}.approve_correction(:c, 'drill')",
                                                          c=own["rows"][0][0])
        call("eli", f"CALL {kb}.reject_correction(:c, 'drill: withdrawn')", c=own["rows"][0][0])
    attacks["Ava reads kb.corrections directly"] = call("ava", f"SELECT * FROM {kb}.corrections")

    # 4. Eli decides, then kb_sync serves the approved corrections.
    for q in spec:
        r = rows[q["id"]]
        if q["decision"] in ("approve", "reject") and r["correction_id"]:
            r["decided"] = call("eli", f"CALL {kb}.{q['decision']}_correction(:c, :why)", c=r["correction_id"],
                                why="drill: checked with the owning team" if q["decision"] == "approve"
                                else "drill: not verified with the acquirer")
    rejected = next(rows[q["id"]]["correction_id"] for q in spec if q["decision"] == "reject")
    attacks["approve a rejected correction"] = call("eli", f"CALL {kb}.approve_correction(:c, 'drill')", c=rejected)
    result["kb_sync_seconds"] = kb_sync()
    approved = [q for q in spec if q["decision"] == "approve"]
    result["seconds_until_indexed"] = {q["id"]: wait_for(q["persona"], q["question"], rows[q["id"]]["correction_id"], True)
                                       for q in approved}

    # 5. The same prompts again, and the test split again.
    for q in spec:
        rows[q["id"]]["after"] = scored(q, ask(q["persona"], q["question"]))
    result["golden_test_after"] = golden_checks()

    # 6. Revert one approved correction: it must stop being served.
    rq = next(q for q in spec if q.get("revert"))
    rr = rows[rq["id"]]
    rr["reverted"] = call("eli", f"CALL {kb}.revert_correction(:c, 'drill: superseded by the updated refund policy')",
                          c=rr["correction_id"])
    result["kb_sync_after_revert_seconds"] = kb_sync()
    result["seconds_until_unindexed"] = wait_for(rq["persona"], rq["question"], rr["correction_id"], False)
    rr["after_revert"] = scored(rq, ask(rq["persona"], rq["question"]))
    result["audit_log"] = sql(people["eli"], f"""SELECT action, count(*) FROM {kb}.audit_log
        WHERE ts >= '{started}' AND action LIKE '%correction%' GROUP BY 1 ORDER BY 1""")

    def passed(split: dict) -> int:
        return sum(1 for c in split.values() if all(v in (True, None) for v in c.values()))

    before, after = passed(result["golden_test_before"]), passed(result["golden_test_after"])
    improved = [q["id"] for q in approved if not rows[q["id"]]["baseline"]["key_fact_stated"]
                and rows[q["id"]]["after"]["key_fact_stated"] and rows[q["id"]]["after"]["cites_correction"]]
    result |= {"rows": rows, "improved": improved, "golden_test_passed": {"before": f"{before}/{len(golden)}",
                                                                          "after": f"{after}/{len(golden)}"}}
    checks = {
        "every gap failed at baseline": all(not r["baseline"]["key_fact_stated"] for r in rows.values()),
        "at least 2 improved after approval": len(improved) >= 2,
        "rejected and unreviewed corrections are not served": all(
            not rows[q["id"]]["after"]["cites_correction"] for q in spec if q["decision"] in ("reject", "leave")),
        "no regression on the test split": after >= before,
        "revert stops the correction being served": result["seconds_until_unindexed"] is not None
            and not rr["after_revert"]["cites_correction"],
        "every attack refused": all(not a["ok"] for a in attacks.values()),
    }
    result["checks"], result["status"] = checks, "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T20" / f"corrections_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scrub(result, principal_names(people["eli"])), indent=2) + "\n")
    for qid, r in rows.items():
        print(qid, r["decision"], "baseline:", r["baseline"]["key_fact_stated"], "after:", r["after"]["key_fact_stated"],
              r["after"]["cited"], "| reverted:", r.get("after_revert", {}).get("cited"))
    for name, a in attacks.items():
        print(f"{'refused' if not a['ok'] else 'ALLOWED':<8} {name}: {a.get('reason', '')}")
    print("test split:", result["golden_test_passed"], "| index wait:", result["seconds_until_indexed"],
          result["seconds_until_unindexed"])
    print(result["status"], json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
