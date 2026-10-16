"""Small helpers for scripts that talk to the workspace from a laptop or CI runner."""

from __future__ import annotations

from meridian.common.localenv import load_local_env

load_local_env()

import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState


def warehouse_id(w: WorkspaceClient) -> str:
    """MERIDIAN_WAREHOUSE_ID if set, else the first serverless SQL warehouse (running ones first)."""
    if os.environ.get("MERIDIAN_WAREHOUSE_ID"):
        return os.environ["MERIDIAN_WAREHOUSE_ID"]
    serverless = [wh for wh in w.warehouses.list() if wh.enable_serverless_compute]
    serverless.sort(key=lambda wh: wh.state.value != "RUNNING")
    if not serverless:
        raise RuntimeError("no serverless SQL warehouse found; set MERIDIAN_WAREHOUSE_ID")
    return serverless[0].id


def sql(w: WorkspaceClient, statement: str, warehouse: str | None = None, timeout_s: int = 300,
        parameters: dict[str, str] | None = None) -> list[list]:
    """Run one statement and return its rows (all values as strings, as the API returns them).

    parameters: named values for :name markers, sent separately from the SQL text (no quoting needed).
    """
    params = [StatementParameterListItem(name=k, value=v) for k, v in (parameters or {}).items()] or None
    resp = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=warehouse or warehouse_id(w), wait_timeout="50s", parameters=params
    )
    deadline = time.time() + timeout_s
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() > deadline:
            raise TimeoutError(statement[:120])
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{resp.status.state.value}: {resp.status.error.message if resp.status.error else ''}"
                           f"\n{statement[:300]}")
    return resp.result.data_array or [] if resp.result else []


def bearer_token(w: WorkspaceClient) -> str:
    return w.config.authenticate()["Authorization"].split(" ", 1)[1]
