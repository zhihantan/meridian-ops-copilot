"""The knowledge chatbot in the browser UI (BUILD): T16's retrieval and grounded answer, as the copilot uses them.

POST /api/knowledge/ask answers one question from the knowledge base. It searches only the indexes of the tiers
the visitor's groups entitle them to, with their own token (meridian.kb.retrieve), and keeps only hits from those
tiers. Code abstains below the tuned reranker threshold; otherwise Claude answers through Unity Gateway as the
visitor and cites each passage (meridian.agent.answer). The response is a short event stream: the passages first,
then the answer.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from databricks_agentkit.runtime.auth import RequestAuthContext
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from meridian.agent.answer import CONFIG, answer, gateway_client
from meridian.kb.retrieve import Hit, Retriever

router = APIRouter(prefix="/api/knowledge")
KB = os.environ.get("MERIDIAN_KB_SCHEMA", "meridian.kb")


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


def passage(h: Hit) -> dict:
    return {"label": f"{h.doc_id} p.{h.page}", "doc_id": h.doc_id, "page": h.page, "title": h.title, "tier": h.tier,
            "version": h.source_version, "modified": (h.modified_at or "")[:10], "score": round(h.score, 3),
            "text": h.text}


@router.post("/ask")
async def ask(body: Question, request: Request) -> StreamingResponse:
    auth = RequestAuthContext.from_headers(request.headers)

    async def stream():
        try:
            w = auth.client_for("user")
            started = time.perf_counter()

            def retrieve() -> tuple[Retriever, list[Hit]]:
                retriever = Retriever(w, KB)
                hits = retriever.search(body.question, CONFIG["retrieval_variant"], CONFIG["top_k"])
                return retriever, [h for h in hits if h.tier in retriever.tiers]  # never a tier they lack

            retriever, hits = await asyncio.to_thread(retrieve)
            searched = time.perf_counter()
            yield event("passages", {"tiers": retriever.tiers, "refused": sorted(retriever.refused),
                                     "threshold": CONFIG["abstain_below_score"], "passages": [passage(h) for h in hits],
                                     "seconds": round(searched - started, 1)})
            result = await asyncio.to_thread(answer, gateway_client(w), body.question, hits)
            yield event("answer", {**result, "citations": [f"{d} p.{p}" for d, p in result["citations"]],
                                   "model": CONFIG["answer_model"], "seconds": round(time.perf_counter() - searched, 1)})
        except Exception as exc:  # noqa: BLE001  shown on the page; the stream ends cleanly
            yield event("error", {"message": f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0][:300]}"})
        finally:
            auth.close()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
