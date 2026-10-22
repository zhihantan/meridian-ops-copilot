"""The copilot's browser UI (BUILD): the React app at /, and the API it calls besides invocations.

The page is the Vite build of apps/copilot/frontend, which scripts/build_copilot.sh writes to runtime/static. The
first chat page stays at /classic, and serves / too when no build is present. Every API request runs as the
visitor (runtime/visitor.py), so Unity Catalog decides what each call may read or do:
- GET /api/me: who the visitor is, the knowledge tiers their groups entitle them to (as search_kb resolves them)
  and whether they are in meridian-admin.
- GET /api/overview: acquirer status from the gold tables, under the visitor's grants.
- GET /api/approvals, /api/approvals/recent: pending, unexpired refund approvals, and the latest decided ones.
  The page asks only for admins; anyone else gets whatever their grants on the approval tables allow.
- POST /api/approvals/{id}: approve one with agent.approve_refund, the SQL SECURITY DEFINER procedure an admin
  would call in SQL. It alone decides (meridian-admin only, never the requester, before the approval expires),
  and its refusal is passed back as it gave it.
- /api/genie (runtime/genie.py) and /api/knowledge (runtime/knowledge.py): Genie and the knowledge chatbot.
- /api/about (runtime/about.py): the workspace links of the About page's architecture.
"""

from __future__ import annotations

import os
from pathlib import Path

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from copilot.workflow import refusal
from meridian.common.workspace import sql, warehouse_id
from meridian.kb.retrieve import entitled_tiers
from runtime import about, genie, knowledge
from runtime.visitor import as_visitor

HERE = Path(__file__).parent
CLASSIC = (HERE / "chat.html").read_text()
STATIC = HERE / "static"
INDEX = (STATIC / "index.html").read_text() if (STATIC / "index.html").exists() else None
NO_CACHE = {"Cache-Control": "no-cache"}  # the page names its hashed assets, so it must never be stale
ADMIN_GROUP = "meridian-admin"  # refund approvers; agent.approve_refund checks its mirror, agent.approvers
PENDING = ("approval_id", "run_id", "acquirer_id", "batch_id", "payments", "total_sgd", "requested_by",
           "requested_sgt", "expires_in_minutes", "mine")
DECIDED = ("approval_id", "batch_id", "acquirer_id", "payments", "total_sgd", "status", "requested_by",
           "approved_by", "decided_sgt", "batch_status", "executed_sgt")
ACQUIRERS = ("acquirer_id", "status", "recent_failure_rate", "baseline_failure_rate", "recent_amount",
             "baseline_daily_amount", "updated_sgt", "data_until_sgt")


def callers(agent: str) -> str:
    """Persona labels from the membership mirrors, as on the dashboard, so no principal ID reaches the page."""
    return f"""
    WITH roles AS (SELECT principal, 'Eli (admin)' AS caller, 0 AS rank FROM {agent}.approvers
                   UNION ALL SELECT principal, 'Ben (finance)', 1 FROM {agent}.tier_members WHERE tier = 'finance'
                   UNION ALL SELECT principal, 'Ava (support)', 2 FROM {agent}.tier_members WHERE tier = 'general'),
         callers AS (SELECT principal, min_by(caller, rank) AS caller FROM roles GROUP BY principal)"""


def pending_sql(agent: str) -> str:
    return f"""{callers(agent)}
    SELECT a.approval_id, a.run_id, r.acquirer_id, a.batch_id, b.payments, a.total_sgd,
           coalesce(c.caller, 'another user'),
           date_format(from_utc_timestamp(a.requested_at, 'Asia/Singapore'), 'dd MMM HH:mm'),
           timestampdiff(MINUTE, current_timestamp(), a.expires_at), a.requested_by = session_user()
    FROM {agent}.approvals a
    LEFT JOIN {agent}.refund_batches b ON b.batch_id = a.batch_id
    LEFT JOIN {agent}.runs r ON r.run_id = a.run_id
    LEFT JOIN callers c ON c.principal = a.requested_by
    WHERE a.status = 'pending' AND a.expires_at > current_timestamp()
    ORDER BY a.requested_at DESC LIMIT 20"""


def decided_sql(agent: str) -> str:
    return f"""{callers(agent)}
    SELECT a.approval_id, a.batch_id, r.acquirer_id, b.payments, a.total_sgd,
           CASE WHEN a.status = 'pending' THEN 'expired' ELSE a.status END,
           coalesce(rq.caller, 'another user'), coalesce(ap.caller, ''),
           date_format(from_utc_timestamp(coalesce(a.decided_at, a.expires_at), 'Asia/Singapore'), 'dd MMM HH:mm'),
           b.status, date_format(from_utc_timestamp(b.executed_at, 'Asia/Singapore'), 'dd MMM HH:mm')
    FROM {agent}.approvals a
    LEFT JOIN {agent}.refund_batches b ON b.batch_id = a.batch_id
    LEFT JOIN {agent}.runs r ON r.run_id = a.run_id
    LEFT JOIN callers rq ON rq.principal = a.requested_by
    LEFT JOIN callers ap ON ap.principal = a.approved_by
    WHERE a.status <> 'pending' OR a.expires_at <= current_timestamp()
    ORDER BY a.status = 'pending', coalesce(a.decided_at, a.expires_at) DESC LIMIT 15"""


def acquirers_sql(gold: str) -> str:
    return f"""SELECT acquirer_id, status, recent_failure_rate, baseline_failure_rate, recent_amount,
           baseline_daily_amount, date_format(from_utc_timestamp(updated_at, 'Asia/Singapore'), 'dd MMM HH:mm'),
           (SELECT date_format(max(hour_sgt) + INTERVAL 1 HOUR, 'dd MMM HH:mm') FROM {gold}.acquirer_hourly)
    FROM {gold}.acquirer_status ORDER BY status = 'degraded' DESC, acquirer_id"""


class Approval(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


def rows_as(columns: tuple[str, ...], statement: str):
    def work(w: WorkspaceClient) -> dict:
        try:
            rows = sql(w, statement, warehouse_id(w))
        except Exception as exc:  # noqa: BLE001  e.g. no grant on these tables
            return {"rows": [], "error": refusal(exc)}
        return {"rows": [dict(zip(columns, r)) for r in rows]}

    return work


def add_ui(app: FastAPI) -> None:
    agent = os.environ.get("MERIDIAN_AGENT_SCHEMA", "meridian.agent")
    gold = os.environ.get("MERIDIAN_GOLD_SCHEMA", "meridian.gold")
    if (STATIC / "assets").is_dir():  # compressed here only: gzip on the app would buffer the event streams
        app.mount("/assets", GZipMiddleware(StaticFiles(directory=STATIC / "assets"), minimum_size=1024), name="assets")

    @app.get("/")
    async def page() -> HTMLResponse:
        return HTMLResponse(INDEX or CLASSIC, headers=NO_CACHE)

    @app.get("/classic")
    async def classic() -> HTMLResponse:
        return HTMLResponse(CLASSIC, headers=NO_CACHE)

    @app.get("/api/me")
    async def me(request: Request) -> dict:
        def work(w: WorkspaceClient) -> dict:
            user = w.current_user.me()
            groups = {g.display for g in user.groups or [] if g.display}
            return {"name": user.display_name or user.user_name, "tiers": entitled_tiers(groups),
                    "admin": ADMIN_GROUP in groups}

        return await as_visitor(request, work)

    @app.get("/api/overview")
    async def overview(request: Request) -> dict:
        result = await as_visitor(request, rows_as(ACQUIRERS, acquirers_sql(gold)))
        return {"acquirers": result["rows"], "error": result.get("error")}

    @app.get("/api/approvals")
    async def approvals(request: Request) -> dict:
        result = await as_visitor(request, rows_as(PENDING, pending_sql(agent)))
        return {"approvals": result["rows"], **({"error": result["error"]} if "error" in result else {})}

    @app.get("/api/approvals/recent")
    async def decided(request: Request) -> dict:
        result = await as_visitor(request, rows_as(DECIDED, decided_sql(agent)))
        return {"approvals": result["rows"], **({"error": result["error"]} if "error" in result else {})}

    @app.post("/api/approvals/{approval_id}")
    async def approve(approval_id: str, body: Approval, request: Request) -> dict:
        if request.headers.get("x-meridian-ui") != "1":  # a cross-site form cannot set it: no forged approvals
            raise HTTPException(400, "missing X-Meridian-UI header")

        def work(w: WorkspaceClient) -> dict:
            try:
                sql(w, f"CALL {agent}.approve_refund(:approval_id, :reason)", warehouse_id(w),
                    parameters={"approval_id": approval_id, "reason": body.reason})
            except Exception as exc:  # noqa: BLE001  the procedure's own refusal, shown as it gave it
                return {"approved": False, "reason": refusal(exc)}
            return {"approved": True}

        return await as_visitor(request, work)

    app.include_router(genie.router)
    app.include_router(knowledge.router)
    app.include_router(about.router)
