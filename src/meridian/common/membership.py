"""Group membership mirrors for the workflow procedures (T18).

Inside a SQL SECURITY DEFINER procedure, group-membership functions check the procedure's owner, not the
caller, so the procedures compare session_user() with two tables instead: agent.approvers (meridian-admin)
and agent.tier_members (the groups of each knowledge tier in config/scenario.yaml). Only workspace admins
can read group membership here (others see groups without members), so an admin refreshes the mirrors with
apply_governance.py, after any membership change.
"""

from __future__ import annotations

from databricks.sdk import WorkspaceClient

from meridian.common.workspace import sql


def members(w: WorkspaceClient, group: str) -> list[str]:
    """A group's direct members as session_user() reports them: a user name, or a service principal's ID."""
    out = []
    for g in w.groups.list(filter=f"displayName eq '{group}'", attributes="members"):
        for member in g.members or []:
            ref = member.ref or ""
            if "ServicePrincipals" in ref:
                out.append(w.service_principals.get(member.value).application_id)
            elif "Users" in ref:
                out.append(w.users.get(member.value).user_name)
    return out


def overwrite(w: WorkspaceClient, table: str, rows: list[tuple[str, str]]) -> None:
    """Replace a (principal, group or tier, synced_at) table's rows in one statement."""
    if not rows:
        sql(w, f"DELETE FROM {table}")
        return
    values = ", ".join(f"(:p{i}, :g{i}, current_timestamp())" for i in range(len(rows)))
    params = {k: v for i, (principal, group) in enumerate(rows)
              for k, v in ((f"p{i}", principal), (f"g{i}", group))}
    sql(w, f"INSERT OVERWRITE {table} VALUES {values}", parameters=params)


def sync(w: WorkspaceClient, agent_schema: str, tiers: dict[str, list[str]]) -> tuple[int, int]:
    """Rewrite both mirrors from live membership; returns (approvers, tier entitlements)."""
    if not any(g.display == "admins" for g in (w.current_user.me().groups or [])):
        raise PermissionError("only a workspace admin can read group membership; run this as an admin")
    approvers = [(principal, "meridian-admin") for principal in members(w, "meridian-admin")]
    overwrite(w, f"{agent_schema}.approvers", approvers)
    entitled = sorted({(principal, tier) for tier, groups in tiers.items()
                       for group in groups for principal in members(w, group)})
    overwrite(w, f"{agent_schema}.tier_members", entitled)
    return len(approvers), len(entitled)
