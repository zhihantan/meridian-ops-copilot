"""Masks and the market row filter in Genie, per asker (T04, T22).

The demo's Genie space has only gold aggregates: no customer contacts and no market column, so the policies have
nothing to apply to there. This probe makes a temporary space over the protected silver tables (payments, which
has the tagged market column, and customers, which has the tagged PII columns). It then asks the same two
questions as Ava, Ben and Eli. Genie runs its SQL as the asker, so the Unity Catalog policies apply:
- Ava (support): only home-market payments, masked email, no NRIC.
- Ben (finance): every market, masked email, no NRIC.
- Eli (admin): everything.
Genie's SQL is recorded; unmasked values are recorded as `<unmasked, N chars>`. The space is deleted at the end.

Writes docs/evidence/T04/genie_probe_<target>.json.

    uv run --group dbx python tests/e2e/genie_governance_probe.py --target dev
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import warehouse_id

REPO = Path(__file__).resolve().parents[2]
PERSONAS = {"ava": "meridian-ava", "ben": "meridian-ben", "eli": None}  # None: the presenter's own profile
GROUPS = ("meridian-support", "meridian-finance", "meridian-admin")
QUESTIONS = {
    "markets": "How many payments are there per country? Show country and count only.",
    "contact": "Show the email, phone and national_id of customer c_00003.",
}


def space(silver: str) -> dict:
    return {"version": 2, "data_sources": {"tables": [
        {"identifier": f"{silver}.customers", "description": ["Customers, one row each. Synthetic data."]},
        {"identifier": f"{silver}.payments", "description": ["Payments, one row each, with the market in country."]}]}}


def ask(w: WorkspaceClient, space_id: str, question: str) -> dict:
    message = w.genie.start_conversation_and_wait(space_id, question)
    out = {"status": str(message.status), "sql": None, "columns": None, "rows": None}
    for a in message.attachments or []:
        if a.query:
            out["sql"] = " ".join((a.query.query or "").split())
            result = w.genie.get_message_attachment_query_result(space_id, message.conversation_id, message.id,
                                                                 a.attachment_id).statement_response
            out["columns"] = [c.name for c in result.manifest.schema.columns] if result and result.manifest else []
            out["rows"] = (result.result.data_array if result and result.result else None) or []
        elif a.text and out["sql"] is None:
            out["text"] = a.text.content
    return out


def scrub(rows: list[list] | None) -> list[list] | None:
    return None if rows is None else [[c if c is None or "***" in str(c) else f"<unmasked, {len(str(c))} chars>"
                                       for c in row] for row in rows]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    args = p.parse_args()
    t = target_names(args.target)
    admin = WorkspaceClient()
    title = f"Meridian governance probe [{args.target}]"
    created = admin.genie.create_space(warehouse_id(admin), json.dumps(space(f"{t.catalog}.{t.schemas['silver']}")),
                                       title=title, description="Temporary: masks and row filters per asker (T04)")
    space_id = created.space_id
    try:
        admin.api_client.do("PATCH", f"/api/2.0/permissions/genie/{space_id}", body={
            "access_control_list": [{"group_name": g, "permission_level": "CAN_RUN"} for g in GROUPS]})
        results = {}
        for persona, profile in PERSONAS.items():
            w = WorkspaceClient(profile=profile) if profile else admin
            results[persona] = {name: ask(w, space_id, q) for name, q in QUESTIONS.items()}
            for name, r in results[persona].items():
                print(f"{persona:4} {name}: {r['sql']} -> {r['rows']}")
    finally:
        admin.genie.trash_space(space_id)

    def column(persona: str, question: str, name: str) -> list:  # by the column's name: Genie picks the order
        r = results[persona][question]
        i = next((i for i, c in enumerate(r["columns"] or []) if name in c.lower()), None)
        return [] if i is None else [row[i] for row in r["rows"] or []]

    def markets(persona: str) -> set[str]:
        return set(column(persona, "markets", "country"))

    checks = {
        "ava_home_market_only": markets("ava") == {"SG"},
        "ben_all_markets": len(markets("ben")) > 1,
        "eli_all_markets": markets("eli") == markets("ben"),
        "ava_email_masked": all("***@" in str(v) for v in column("ava", "contact", "email") or [""]),
        "ava_nric_hidden": column("ava", "contact", "national") == [None],
        "ben_email_masked": all("***@" in str(v) for v in column("ben", "contact", "email") or [""]),
        "eli_sees_raw_email": any("@" in str(v) and "***" not in str(v) for v in column("eli", "contact", "email")),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    for persona in results:
        results[persona]["contact"]["rows"] = scrub(results[persona]["contact"]["rows"])
    out = REPO / "docs" / "evidence" / "T04" / f"genie_probe_{args.target}.json"
    out.write_text(json.dumps({"target": args.target, "ran_at": datetime.now(UTC).isoformat(), "space": title,
                               "questions": QUESTIONS, "results": results, "checks": checks, "status": status},
                              indent=2, default=str) + "\n")
    print(checks, status)


if __name__ == "__main__":
    main()
