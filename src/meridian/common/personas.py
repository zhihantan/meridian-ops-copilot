"""Persona names for principals in published evidence (the presenter plays Eli; Ava, Ben and Gus are service
principals). Evidence files show who did what by persona, never a person's user name."""

from __future__ import annotations

import json

from databricks.sdk import WorkspaceClient

PROFILES = {"ava": "meridian-ava", "ben": "meridian-ben", "gus": "meridian-gus"}


def principal_names(admin: WorkspaceClient) -> dict[str, str]:
    """{principal as session_user() reports it: persona} for the presenter (eli) and the persona profiles."""
    names = {WorkspaceClient(profile=prof).current_user.me().user_name: persona for persona, prof in PROFILES.items()}
    return names | {admin.current_user.me().user_name: "eli"}


def scrub(obj, names: dict[str, str]):
    """obj with every known principal replaced by its persona name, anywhere in its strings."""
    text = json.dumps(obj, default=str)
    for principal, persona in sorted(names.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(principal, persona)
    return json.loads(text)
