"""Create the persona groups and set their members (Day 0; idempotent, also used by demo reset).

Groups must be account-level, because Unity Catalog cannot grant to workspace-local groups. They are
created through the account SCIM API that the workspace host proxies. Personas we cannot log in as
are service principals; the presenter plays Eli and Fay.

    uv run --group dbx python scripts/setup_identities.py
"""

from __future__ import annotations

from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

SCENARIO = Path(__file__).resolve().parents[1] / "config" / "scenario.yaml"
GROUPS_API = "/api/2.0/account/scim/v2/Groups"
SERVICE_PRINCIPAL_FOR = {"ava": "meridian-ava", "ben": "meridian-ben", "gus": "meridian-gus"}
PRESENTER = {"eli", "fay"}


def ensure_group(w: WorkspaceClient, name: str) -> str:
    found = w.api_client.do("GET", GROUPS_API, query={"filter": f'displayName eq "{name}"', "attributes": "id"})
    if found.get("totalResults"):
        return found["Resources"][0]["id"]
    body = {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": name}
    return w.api_client.do("POST", GROUPS_API, body=body)["id"]


def set_members(w: WorkspaceClient, group_id: str, member_ids: set[str]) -> None:
    """Replace membership exactly, so a reset undoes live changes such as removing Ben from finance."""
    body = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "members", "value": [{"value": m} for m in sorted(member_ids)]}],
    }
    w.api_client.do("PATCH", f"{GROUPS_API}/{group_id}", body=body)


def assign_to_workspace(w: WorkspaceClient, principal_id: str) -> None:
    w.api_client.do("PUT", f"/api/2.0/preview/permissionassignments/principals/{principal_id}",
                    body={"permissions": ["USER"]})


def main() -> None:
    scenario = yaml.safe_load(SCENARIO.read_text())
    w = WorkspaceClient()
    me = w.current_user.me()
    sps = {sp.display_name: sp.id for sp in w.service_principals.list(filter='displayName sw "meridian-"')}

    members: dict[str, set[str]] = {}
    for persona, spec in scenario["personas"].items():
        principal = me.id if persona in PRESENTER else sps[SERVICE_PRINCIPAL_FOR[persona]]
        for group in spec["groups"]:
            members.setdefault(group, set()).add(principal)

    names = {me.id: me.user_name, **{v: k for k, v in sps.items()}}
    for group, ids in sorted(members.items()):
        group_id = ensure_group(w, group)
        set_members(w, group_id, ids)
        assign_to_workspace(w, group_id)
        print(f"{group} ({group_id}): {', '.join(sorted(names[i] for i in ids))}")


if __name__ == "__main__":
    main()
