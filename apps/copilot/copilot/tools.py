"""Copilot tools (T17, BUILD). Every tool runs as the verified caller; security decisions are code.

search_kb searches only the indexes the caller's groups entitle them to (meridian.kb.retrieve), with the
caller's own token, drops any hit outside those tiers before the model sees it, and returns nothing when the
best hit scores below the abstention threshold. ask_genie is a stub until the Genie space exists (T22).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.entities import Document, SpanType

from meridian.agent.answer import CONFIG
from meridian.kb.retrieve import Retriever

DEFINITIONS = [
    {"name": "search_kb",
     "description": "Search Meridian's knowledge base (runbooks, policies, fee schedules, #ops-incidents). "
                    "Returns passages labelled like [DOC-RB-014 p.1]; cite those labels.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "ask_genie",
     "description": "Ask a question about payments data (failure rates, volumes, acquirers) in plain English.",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
]


@dataclass
class Caller:
    principal: str            # verified identity: Apps ingress in deployment, the local profile in development
    client: WorkspaceClient   # acts as the caller


class Tools:
    def __init__(self, caller: Caller):
        self.caller = caller
        self.retriever = Retriever(caller.client, os.environ.get("MERIDIAN_KB_SCHEMA", "meridian.kb"))

    @property
    def tiers(self) -> list[str]:
        return self.retriever.tiers

    def call(self, name: str, args: dict) -> dict:
        if name == "search_kb":
            return self.search_kb(str(args.get("query", "")))
        if name == "ask_genie":
            return {"status": "not_connected", "note": "Genie is not connected yet; answer from the knowledge base."}
        return {"error": f"unknown tool {name}"}

    def search_kb(self, query: str) -> dict:
        with mlflow.start_span(name="search_kb", span_type=SpanType.RETRIEVER) as span:
            span.set_inputs({"query": query, "tiers": self.tiers})
            hits = self.retriever.search(query, CONFIG["retrieval_variant"], CONFIG["top_k"])
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
