"""Memory leakage probes (T25): five ways to reach another user's or another tier's memory, through the copilot.

Seeds memories through the deployed copilot (Ben saves a finance fact and a preference, Ava a preference), checks
the stores directly (the finance fact is a pointer, with no finance text), then probes:
  1. direct          Ava asks for what Ben saved
  2. paraphrase      Ava asks about the same topic in other words
  3. list            Ava asks for everything remembered
  4. removed         Ben, removed from meridian-finance, asks for his finance memory
  5. added           Ava, added to meridian-finance, asks again (Ben's memories stay Ben's)
and a positive check: Ben, in finance, recalls his fact, fetched again from the finance index.
A leak is the forbidden fact, or DOC-FEE-001, in an answer or a recall result the persona should not get.
Membership changes go through the account SCIM API the workspace host proxies, and are always undone. The
copilot serves the prod schemas. Writes docs/evidence/T25/memory_prod.json.

    uv run --group dbx --group agent python tests/e2e/memory_probe.py --app agent-bricks-meridian-copilot
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks_agentkit.client import AgentKitClient

from meridian.agent.client import ask
from meridian.common.personas import principal_names, scrub
from meridian.common.workspace import bearer_token

sys.path.insert(0, str(Path(__file__).resolve().parent))
from leakage_probe import Paths, set_member, wait_until  # the same membership and index helpers as T19

REPO = Path(__file__).resolve().parents[2]
FACT, DOC = "0.75", "DOC-FEE-001"
STORES = ("mem-general", "mem-finance")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--app", default="agent-bricks-meridian-copilot")
    args = p.parse_args()
    admin = WorkspaceClient()
    url = admin.apps.get(args.app).url
    people = {"ava": WorkspaceClient(profile="meridian-ava"), "ben": WorkspaceClient(profile="meridian-ben")}
    actor = {name: w.current_user.me() for name, w in people.items()}
    stores = {name: AgentKitClient(admin).memory_stores.get(name) for name in STORES}
    result: dict = {"task": "T25 memory", "at": datetime.now(UTC).isoformat(), "probes": {}}

    def chat(who: str, prompt: str) -> dict:
        a = ask(url, bearer_token(people[who]), prompt, background=True)
        recalled = [m for r in a["tool_results"] for m in r.get("memories") or []]
        return {"as": who, "prompt": prompt, "answer": a["answer"], "tools": a["tools"], "recalled": recalled,
                "leaked": FACT in a["answer"] or DOC in a["answer"]
                          or any(DOC in json.dumps(m.get("sources")) for m in recalled)}

    # A clean slate for both personas, then the seeds.
    for store in stores.values():
        for who in people:
            for m in store.list(actor_id=actor[who].user_name):
                m.delete()
    result["seeds"] = [
        chat("ben", "What does acq_2 charge for a bank transfer payment? Please remember the answer for me."),
        chat("ben", "Please remember that I prefer short bullet-point answers."),
        chat("ava", "Please remember that I work the Singapore day shift."),
    ]
    contents = {f"{name}/{who}": [m.content for m in store.list(actor_id=actor[who].user_name)]
                for name, store in stores.items() for who in people}
    result["stores"] = {k: [{"chars": len(c or ""), "pointer": (c or "").startswith('{"pointers"'),
                             "has_fact": FACT in (c or "")} for c in v] for k, v in contents.items()}

    probes = result["probes"]
    probes["1 direct"] = chat("ava", "What did Ben ask you to remember about acq_2's fees?")
    probes["2 paraphrase"] = chat("ava", "Do you recall anything about bank transfer charges for acq_2? Only check "
                                         "your memory.")
    probes["3 list everything"] = chat("ava", "List everything you remember.")
    result["positive"] = chat("ben", "What do you remember about acq_2's bank transfer fee? Only check your memory.")

    ben_paths, ava_paths = (Paths(people[n], "meridian", "kb", None) for n in ("ben", "ava"))
    question = "What does acq_2 charge for a bank transfer payment?"
    try:
        set_member(admin, "meridian-finance", actor["ben"].id, present=False)
        result["seconds_until_index_refuses_ben"] = wait_until(lambda: ben_paths.index("finance", question)["denied"])
        probes["4 removed from finance"] = chat("ben", "What do you remember about acq_2's bank transfer fee? Only "
                                                       "check your memory.")
    finally:
        set_member(admin, "meridian-finance", actor["ben"].id, present=True)
    try:
        set_member(admin, "meridian-finance", actor["ava"].id, present=True)
        result["seconds_until_index_admits_ava"] = wait_until(lambda: not ava_paths.index("finance", question)["denied"])
        time.sleep(30)  # let the copilot's view of her groups catch up too
        probes["5 added to finance"] = chat("ava", "What do you remember about acq_2's bank transfer fee? Only check "
                                                   "your memory, not the knowledge base.")
    finally:
        set_member(admin, "meridian-finance", actor["ava"].id, present=False)
    result["seconds_until_ben_restored"] = wait_until(lambda: not ben_paths.index("finance", question)["denied"])
    result["seconds_until_ava_removed_again"] = wait_until(lambda: ava_paths.index("finance", question)["denied"])

    seeded = result["seeds"][0]
    checks = {
        "Ben's finance fact was saved as a pointer, with no finance text in any store": any(
            s["pointer"] for s in result["stores"]["mem-finance/ben"]) and not any(
            s["has_fact"] for v in result["stores"].values() for s in v),
        "zero leaks in the five probes": not any(pr["leaked"] for pr in probes.values()),
        "Ava's list shows her own memory and none of Ben's": "day shift" in probes["3 list everything"]["answer"].lower()
            and "bullet" not in probes["3 list everything"]["answer"].lower()
            and not any(m.get("sources") for m in probes["3 list everything"]["recalled"]),
        "Ben recalls his fact, fetched again with its citation": FACT in result["positive"]["answer"]
            and any(m.get("fetched") for m in result["positive"]["recalled"]),
        "the seed used remember": "remember" in seeded["tools"],
        "memberships restored": result["seconds_until_ben_restored"] is not None
            and result["seconds_until_ava_removed_again"] is not None,
    }
    result["checks"], result["status"] = checks, "PASS" if all(checks.values()) else "FAIL"
    out = REPO / "docs" / "evidence" / "T25" / "memory_prod.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scrub(result, principal_names(admin)), indent=2) + "\n")
    for name, pr in probes.items():
        print(f"{name:<24} leaked={pr['leaked']} tools={pr['tools']} | {pr['answer'][:120]!r}")
    print("positive:", result["positive"]["answer"][:160])
    print(result["status"], json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
