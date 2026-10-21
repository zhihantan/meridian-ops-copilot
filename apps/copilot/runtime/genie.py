"""Genie in the browser UI (BUILD over the NATIVE Genie space "Meridian payments (gold)", T22).

The visitor asks the space directly. POST /api/genie/ask starts a conversation, or continues one, and returns at
once; the page then polls GET /api/genie/{conversation_id}/{message_id} until Genie has answered, and gets its
text, SQL and rows. Genie runs the SQL with the visitor's grants, masks and row filters, so two people can get
different rows for the same question.
"""

from __future__ import annotations

import os

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from runtime.visitor import as_visitor

router = APIRouter(prefix="/api/genie")
TITLE = os.environ.get("MERIDIAN_GENIE_TITLE", "Meridian payments (gold)")
ROWS = 500  # rows sent to the page per query
DONE = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}
_spaces: dict[str, str] = {}  # title: space id. Ids are not per person; Genie checks access on every call.


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=100)


def space_id(w: WorkspaceClient) -> str:
    if TITLE not in _spaces:
        spaces = w.genie.list_spaces().spaces or []
        found = next((s.space_id for s in spaces if s.title == TITLE), None)
        if not found:
            raise HTTPException(404, f"The Genie space '{TITLE}' is not available to you.")
        _spaces[TITLE] = found
    return _spaces[TITLE]


def shape(w: WorkspaceClient, path: str, message: dict) -> dict:
    """A Genie message as the page shows it. Rows are fetched once the message is complete."""
    status = message.get("status") or "SUBMITTED"
    out: dict = {"status": status, "done": status in DONE, "text": None, "queries": [], "suggestions": [],
                 "error": None}
    for attachment in message.get("attachments") or []:
        aid = attachment.get("attachment_id") or ""
        if (attachment.get("text") or {}).get("content"):
            out["text"] = attachment["text"]["content"]
        query = attachment.get("query") or {}
        if query.get("query"):
            item = {"label": f"GENIE-{aid[-8:]}", "title": query.get("title"), "description": query.get("description"),
                    "sql": query.get("query"), "row_count": (query.get("query_result_metadata") or {}).get("row_count"),
                    "columns": [], "rows": [], "truncated": False}
            if status == "COMPLETED":
                result = w.api_client.do("GET", f"{path}/attachments/{aid}/query-result").get("statement_response") or {}
                columns = ((result.get("manifest") or {}).get("schema") or {}).get("columns") or []
                rows = (result.get("result") or {}).get("data_array") or []
                item.update(columns=[{"name": c.get("name"), "type": c.get("type_name")} for c in columns],
                            rows=rows[:ROWS], truncated=len(rows) > ROWS)
            out["queries"].append(item)
        suggested = attachment.get("suggested_questions") or {}
        if isinstance(suggested, dict) and suggested.get("questions"):
            out["suggestions"] = [str(q) for q in suggested["questions"]][:4]
    error = message.get("error")
    if error:
        out["error"] = error.get("error") if isinstance(error, dict) else str(error)
    return out


@router.get("/space")
async def space(request: Request) -> dict:
    def work(w: WorkspaceClient) -> dict:
        sid = space_id(w)
        info = w.api_client.do("GET", f"/api/2.0/genie/spaces/{sid}")
        return {"space_id": sid, "title": info.get("title") or TITLE, "description": info.get("description"),
                "url": f"{w.config.host.rstrip('/')}/genie/rooms/{sid}"}

    return await as_visitor(request, work)


@router.post("/ask")
async def ask(body: Ask, request: Request) -> dict:
    def work(w: WorkspaceClient) -> dict:
        sid = space_id(w)
        if body.conversation_id:
            sent = w.api_client.do("POST", f"/api/2.0/genie/spaces/{sid}/conversations/{body.conversation_id}/messages",
                                   body={"content": body.question})
            return {"conversation_id": body.conversation_id, "message_id": sent.get("message_id") or sent.get("id")}
        started = w.api_client.do("POST", f"/api/2.0/genie/spaces/{sid}/start-conversation",
                                  body={"content": body.question})
        return {"conversation_id": started["conversation_id"], "message_id": started["message_id"]}

    return await as_visitor(request, work)


@router.get("/{conversation_id}/{message_id}")
async def message(conversation_id: str, message_id: str, request: Request) -> dict:
    def work(w: WorkspaceClient) -> dict:
        path = f"/api/2.0/genie/spaces/{space_id(w)}/conversations/{conversation_id}/messages/{message_id}"
        return shape(w, path, w.api_client.do("GET", path))

    return await as_visitor(request, work)
