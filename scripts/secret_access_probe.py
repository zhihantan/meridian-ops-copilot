"""Who can read a Unity Catalog secret (T08): try it as each persona; collect the audit rows. Read-only.

Each persona (its own CLI profile) asks for the value; the evidence keeps allowed or denied and, when
allowed, the fingerprint only. --audit adds the matching system.access.audit rows (not real-time).

    uv run --group dbx python scripts/secret_access_probe.py --target dev --secret t08_probe [--audit]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import sql

REPO = Path(__file__).resolve().parents[1]
PERSONAS = {"eli (admin, secret owner)": None, "gus (data engineer)": "meridian-gus", "ava (support)": "meridian-ava"}


def try_read(profile: str | None, full_name: str) -> dict:
    w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    try:
        secret = w.api_client.do("GET", f"/api/2.1/unity-catalog/secrets/{full_name}", query={"include_value": "true"})
        value = secret.get("effective_value") or ""
        return {"result": "allowed", "fingerprint": hashlib.sha256(value.encode()).hexdigest()[:12]}
    except Exception as exc:  # noqa: BLE001  a denial is the expected outcome for some personas
        message = str(exc).splitlines()[0].split(" Config:")[0]  # the SDK appends the host; evidence is public
        return {"result": "denied", "error": type(exc).__name__, "message": message[:120]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    p.add_argument("--secret", default="t08_probe")
    p.add_argument("--audit", action="store_true")
    args = p.parse_args()
    t = target_names(args.target)
    full_name = f"{t.catalog}.secrets.{args.secret}"
    result: dict = {"task": "T08 secret access", "target": args.target, "secret": full_name,
                    "at": datetime.now(UTC).isoformat(), "reads": {}}
    for persona, profile in PERSONAS.items():
        result["reads"][persona] = try_read(profile, full_name)
        print(f"{persona:<28} {result['reads'][persona]['result']}")
    if args.audit:
        rows = sql(WorkspaceClient(), f"""
            SELECT event_time, action_name, user_identity.email, response.status_code,
                   request_params['full_name_arg'], request_params['include_value']
            FROM system.access.audit
            WHERE event_date >= current_date() - INTERVAL 2 DAYS AND service_name = 'unityCatalog'
              AND action_name ILIKE '%secret%' AND to_json(request_params) LIKE '%{full_name}%'
            ORDER BY event_time DESC LIMIT 40""")
        result["audit"] = [dict(zip(("event_time", "action", "principal", "status", "secret", "include_value"),
                                    [r[0], r[1], "<user>" if r[2] and "@" in r[2] else r[2], *r[3:]])) for r in rows]
        print(f"{len(result['audit'])} audit rows")
    out = REPO / "docs" / "evidence" / "T08" / f"access_{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
