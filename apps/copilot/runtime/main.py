"""Serve the copilot through Agent Bricks' DurableAgentServer (T17): sync, streaming and background calls, and
its browser UI (runtime/ui.py, BUILD): the chat page at / that makes those calls, and the approvals it shows.

The caller is whoever the Databricks Apps ingress authenticated. agent.toml requires user auth, so each
invocation carries the caller's own downscoped token and every tool runs as them. There is no fallback to
the app's identity: without a caller token the invocation fails. In local development (agentbricks dev),
MERIDIAN_CALLER_PROFILE names the persona profile to act as.
"""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
import uvicorn
from databricks.sdk import WorkspaceClient
from databricks_agentkit import DurableAgentServer, InvocationContext
from databricks_agentkit.runtime.auth import AuthError
from databricks_agentkit.runtime.tracing import configure_tracing, start_trace
from dotenv import load_dotenv

from copilot.loop import run
from copilot.tools import Caller, Tools
from runtime.ui import add_ui

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)
configure_tracing(mlflow.anthropic.autolog)


def resolve_caller(context: InvocationContext) -> Caller:
    if os.getenv("DATABRICKS_APP_NAME"):  # deployed: the ingress-verified caller, never the app itself
        if context.request_auth is None:
            raise AuthError("MERIDIAN_CALLER_REQUIRED", "The copilot needs the caller's identity", 401)
        client = context.request_auth.client_for("user")
    else:
        profile = os.getenv("MERIDIAN_CALLER_PROFILE")
        client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    me = client.current_user.me()
    return Caller(principal=me.user_name or me.display_name or "unknown", client=client)


async def invoke(value, context: InvocationContext) -> dict:
    payload = {"messages": value} if isinstance(value, list) else dict(value or {})
    messages = payload.get("messages") or []
    caller = resolve_caller(context)
    tools = Tools(caller)
    tools.question = next((str(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    outputs: list[dict] = []

    async def emit(event: dict) -> int:
        outputs.append(event["message"])
        return await context.emit(event)

    with start_trace("meridian-copilot", inputs={"messages": messages}, session_id=context.session_id):
        if mlflow.get_current_active_span():  # tracing is off when no experiment is configured
            mlflow.update_current_trace(tags={"agent": "meridian-copilot", "user": caller.principal,
                                              "tiers": ",".join(tools.tiers), "invocation": context.invocation_id})
        await run(tools, messages, emit)
    return {"output": outputs, "status": "completed"}


app = DurableAgentServer()
app.invoke(invoke)
app.recover(invoke)  # request-user work is never resumed by the runtime; app-auth work would replay
add_ui(app)


def main() -> None:
    uvicorn.run("runtime.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
