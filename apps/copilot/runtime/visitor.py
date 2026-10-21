"""The visitor's own Databricks client for the browser UI's API (BUILD), from the Apps ingress headers.

The ingress signs the visitor in and forwards their downscoped token, as it does for invocations, so every call
made with this client is checked by Unity Catalog, Genie and AI Search as that person. In local development the
runtime ignores the headers and uses the developer's own profile.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from databricks.sdk import WorkspaceClient
from databricks_agentkit.runtime.auth import RequestAuthContext
from fastapi import Request

T = TypeVar("T")


async def as_visitor(request: Request, work: Callable[[WorkspaceClient], T]) -> T:
    """Run work in a thread with a client acting as the visitor; the credentials are dropped afterwards."""
    auth = RequestAuthContext.from_headers(request.headers)
    try:
        return await asyncio.to_thread(work, auth.client_for("user"))
    finally:
        auth.close()
