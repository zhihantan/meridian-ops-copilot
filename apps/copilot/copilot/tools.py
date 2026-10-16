"""Copilot tools (T17, BUILD). Every tool runs as the verified caller; security decisions are code.

search_kb searches only the indexes the caller's groups entitle them to (meridian.kb.retrieve), with the
caller's own token, drops any hit outside those tiers before the model sees it, and returns nothing when the
best hit scores below the abstention threshold. ask_genie asks the Genie space as the caller (T22), so Genie's
SQL runs under the caller's grants and ABAC policies; results come back with a citable Genie label.
start_workflow and run_step drive governed runbook runs step by step (T18, copilot/workflow.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.entities import Document, SpanType

from copilot import workflow
from meridian.agent.answer import CONFIG
from meridian.kb.retrieve import Retriever

DEFINITIONS = [
    {"name": "search_kb",
     "description": "Search Meridian's knowledge base (runbooks, policies, fee schedules, #ops-incidents). "
                    "Returns passages labelled like [DOC-RB-014 p.1]; cite those labels.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "ask_genie",
     "description": "Ask the payments data (failure rates, volumes, refundable amounts, acquirer status) in plain "
                    "English. Returns Genie's SQL and rows labelled like [GENIE-1a2b3c4d]; cite that label.",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    *workflow.DEFINITIONS,
]


@dataclass
class Caller:
    principal: str            # verified identity: Apps ingress in deployment, the local profile in development
    client: WorkspaceClient   # acts as the caller


class Tools:
    def __init__(self, caller: Caller):
        self.caller = caller
        self.retriever = Retriever(caller.client, os.environ.get("MERIDIAN_KB_SCHEMA", "meridian.kb"))
        self.workflows = workflow.Workflows(self)

    @property
    def tiers(self) -> list[str]:
        return self.retriever.tiers

    def call(self, name: str, args: dict) -> dict:
        if name == "search_kb":
            return self.search_kb(str(args.get("query", "")))
        if name == "ask_genie":
            return self.ask_genie(str(args.get("question", "")))
        if name == "start_workflow":
            return self.workflows.start(str(args.get("workflow_id", "")), str(args.get("acquirer_id", "")),
                                        args.get("window_hours", 0))
        if name == "run_step":
            return self.workflows.step(str(args.get("run_id", "")), str(args.get("step_id", "")))
        return {"error": f"unknown tool {name}"}

    def search_kb(self, query: str, only: list[str] | None = None) -> dict:
        with mlflow.start_span(name="search_kb", span_type=SpanType.RETRIEVER) as span:
            span.set_inputs({"query": query, "tiers": [t for t in self.tiers if only is None or t in only]})
            hits = self.retriever.search(query, CONFIG["retrieval_variant"], CONFIG["top_k"], only)
            if self.retriever.refused:
                span.set_attribute("tiers_refused_by_index", sorted(self.retriever.refused))
            hits = [h for h in hits if h.tier in self.tiers]  # never a chunk from a tier the caller lacks
            if not hits or hits[0].score < CONFIG["abstain_below_score"]:
                hits = []
            span.set_outputs([Document(page_content=h.text, metadata={"doc_uri": h.doc_id, "page": h.page,
                                                                      "tier": h.tier, "score": h.score})
                              for h in hits])
        if not hits:
            return {"results": [], "note": "Nothing in the knowledge base is relevant enough to answer this."}
        return {"results": [{"source": f"[{h.doc_id} p.{h.page}]", "title": h.title, "version": h.source_version,
                             "modified": (h.modified_at or "")[:10], "text": h.text} for h in hits]}

    def genie_space_id(self) -> str | None:
        if not hasattr(self, "_space_id"):
            title = os.environ.get("MERIDIAN_GENIE_TITLE", "Meridian payments (gold)")
            spaces = self.caller.client.genie.list_spaces().spaces or []
            self._space_id = next((sp.space_id for sp in spaces if sp.title == title), None)
        return self._space_id

    def ask_genie(self, question: str) -> dict:
        with mlflow.start_span(name="ask_genie", span_type=SpanType.TOOL) as span:
            span.set_inputs({"question": question})
            space_id = self.genie_space_id()
            if not space_id:
                return {"error": "the Genie space is not available to this caller"}
            g = self.caller.client.genie
            try:
                msg = g.start_conversation_and_wait(space_id, question)
            except Exception as exc:  # noqa: BLE001  a failed Genie message is a tool result, not a crash
                span.set_outputs({"error": str(exc)[:300]})
                return {"error": f"Genie could not answer: {str(exc)[:200]}. Rephrase or narrow the question."}
            out: dict = {"text": None, "queries": []}
            for att in msg.attachments or []:
                if att.text and att.text.content:
                    out["text"] = att.text.content
                if att.query and att.query.query:
                    res = g.get_message_attachment_query_result(space_id, msg.conversation_id, msg.message_id,
                                                                att.attachment_id).statement_response
                    columns = [c.name for c in (res.manifest.schema.columns or [])] if res and res.manifest else []
                    rows = (res.result.data_array or [])[:20] if res and res.result else []
                    out["queries"].append({"source": f"[GENIE-{att.attachment_id[-8:]}]",  # IDs share a time prefix
                                           "genie_query_id": att.attachment_id, "conversation_id": msg.conversation_id,
                                           "sql": att.query.query, "description": att.query.description,
                                           "columns": columns, "rows": rows})
            span.set_outputs(out)
        return out
