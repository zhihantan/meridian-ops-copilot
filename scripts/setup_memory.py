"""Memory stores for the copilot (T25): mem-general and mem-finance, and the deployed app's access to them.

Agent Bricks managed memory stores (PREVIEW) hold long-term memory, each entry partitioned by an actor ID that
the caller of the API chooses. agent.toml binds a single store and this design needs one per knowledge tier,
so both are created here and the app's service principal gets WRITE on each. People never reach a store
directly: the copilot's code picks the store and the actor (apps/copilot/copilot/memory.py), and finance facts
are kept as pointers that are re-fetched as the caller.

    uv run --group dbx --group agent python scripts/setup_memory.py --app agent-bricks-meridian-copilot
"""

from __future__ import annotations

import argparse

from databricks.sdk import WorkspaceClient
from databricks_agentkit.client import AgentKitClient

STORES = {"mem-general": "Copilot memory: preferences, procedures and general-tier facts, per user (T25)",
          "mem-finance": "Copilot memory: pointers to finance-tier sources, per user; content is re-fetched (T25)"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--app", default="agent-bricks-meridian-copilot")
    args = p.parse_args()
    w = WorkspaceClient()
    app_sp = w.apps.get(args.app).service_principal_client_id
    client = AgentKitClient(w)
    existing = {s.display_name: s for s in client.memory_stores.list()}
    for name, description in STORES.items():
        store = existing.get(name) or client.memory_stores.create(name, description=description)
        store.grant_permission(app_sp, permission="WRITE")
        print(f"{name} ({store.id}): {'exists' if name in existing else 'created'}; WRITE for the app's principal")


if __name__ == "__main__":
    main()
