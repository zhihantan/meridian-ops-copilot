"""Long-term memory (T25): Agent Bricks managed memory stores (PREVIEW); the rules are BUILD, in code.

Two stores, mem-general and mem-finance (scripts/setup_memory.py). The code, never the model, decides:
- whose memory: the actor is the verified caller, so nobody reads or writes another person's memories;
- where it goes: the highest tier among the knowledge sources used in this invocation. Anything remembered
  after a finance passage was read goes to mem-finance; otherwise preferences, procedures and facts go to
  mem-general;
- what is kept: a finance fact is kept as a pointer (document, page, version and the question it answered),
  never the finance text. At recall the passage is fetched again from the finance index as the caller, so
  someone who has lost finance access recalls nothing of it;
- what is read: mem-general always, mem-finance only for callers entitled to the finance tier.
The memory API is called with the app's own identity, which holds the stores' grants; people have no direct
access to the stores.
"""

from __future__ import annotations

import json
import os
import uuid

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_agentkit.client import AgentKitClient
from mlflow.entities import SpanType

from meridian.agent.answer import CONFIG

STORES = {"general": os.environ.get("MERIDIAN_MEMORY_GENERAL", "mem-general"),
          "finance": os.environ.get("MERIDIAN_MEMORY_FINANCE", "mem-finance")}
RANK = {"general": 0, "finance": 1}

DEFINITIONS = [
    {"name": "remember",
     "description": "Save something for this user to recall in later conversations: a preference, a procedure "
                    "they follow, or a fact from this conversation's sources. Where and how it is kept is decided "
                    "for you; memories belong to this user only.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["preference", "procedure", "fact"]},
         "text": {"type": "string", "description": "what to remember, in one or two sentences"}},
         "required": ["kind", "text"]}},
    {"name": "recall",
     "description": "Recall what this user asked you to remember earlier. Pass a topic, or an empty query to list "
                    "everything. Facts from restricted sources are fetched again, as the user, when recalled.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]


class Memory:
    def __init__(self, tools):  # copilot.tools.Tools: the verified caller, their tiers, retriever and sources used
        self.tools = tools
        self._client: AgentKitClient | None = None
        self._stores: dict = {}

    def store(self, tier: str):
        if tier not in self._stores:
            self._client = self._client or AgentKitClient(WorkspaceClient())  # the app's identity, not the caller's
            self._stores[tier] = self._client.memory_stores.get(STORES[tier])
        return self._stores[tier]

    def remember(self, kind: str, text: str) -> dict:
        with mlflow.start_span(name="remember", span_type=SpanType.TOOL) as span:
            used = self.tools.sources_used
            tier = max((s["tier"] for s in used), key=RANK.__getitem__, default="general")
            if tier == "finance" and kind == "fact":  # a pointer only; the passage is re-fetched at recall
                content = json.dumps({"pointers": sorted({(s["doc_id"], s["page"], s["version"] or "")
                                                          for s in used if s["tier"] == "finance"}),
                                      "question": self.tools.question})
            else:
                content = " ".join(text.split())[:1000]
            path = f"/{kind}s/{uuid.uuid4().hex[:10]}.md"
            self.store(tier).add(actor_id=self.tools.caller.principal, path=path, content=content, description=kind)
            out = {"saved": True, "kind": kind, "kept_as": "pointer to the finance source" if content.startswith("{")
                   else "text", "tier": tier}
            span.set_inputs({"kind": kind, "sources_tiers": sorted({s["tier"] for s in used})})
            span.set_outputs(out | {"store": STORES[tier]})
        return out

    def recall(self, query: str) -> dict:
        with mlflow.start_span(name="recall", span_type=SpanType.RETRIEVER) as span:
            readable = ["general"] + (["finance"] if "finance" in self.tools.tiers else [])
            span.set_inputs({"query": query, "stores": [STORES[t] for t in readable]})
            memories = []
            for tier in readable:
                store, actor = self.store(tier), self.tools.caller.principal
                entries = ([r.memory for r in store.search(actor_id=actor, query=query, limit=10)] if query.strip()
                           else list(store.list(actor_id=actor)))
                for m in entries:
                    if (m.content or "").startswith('{"pointers"'):
                        memories.append(self.refetch(m))
                    else:
                        memories.append({"kind": m.description, "text": m.content, "saved": str(m.create_time)[:10]})
            span.set_outputs([{"kind": m["kind"], "sources": m.get("sources")} for m in memories])
        return {"memories": memories} if memories else {"memories": [], "note": "Nothing remembered for this user."}

    def refetch(self, m) -> dict:
        """A finance pointer's passage, fetched now as the caller; nothing if the index refuses or it is gone."""
        ref = json.loads(m.content)
        wanted = {(doc, int(page)) for doc, page, _ in ref["pointers"]}
        hits = self.tools.retriever.search(ref["question"], CONFIG["retrieval_variant"], CONFIG["top_k"], ["finance"])
        hits = [h for h in hits if (h.doc_id, h.page) in wanted and h.tier in self.tools.tiers]
        if not hits:
            return {"kind": m.description, "text": None, "note": "its finance source could not be fetched for you"}
        self.tools.sources_used += [{"doc_id": h.doc_id, "page": h.page, "tier": h.tier, "version": h.source_version}
                                    for h in hits]  # what is remembered next in this invocation inherits the tier
        versions = {doc: version for doc, _, version in ref["pointers"]}
        return {"kind": m.description, "question": ref["question"], "sources": [f"[{h.doc_id} p.{h.page}]" for h in hits],
                "text": " ".join(h.text for h in hits),
                "changed_since_saved": any(versions.get(h.doc_id) not in ("", h.source_version) for h in hits)}
