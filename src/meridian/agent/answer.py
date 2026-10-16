"""Grounded answers with citations (T16, T17): Claude through Unity Gateway's native Anthropic path.

The model sees only chunks the retriever returned for this caller, already limited to the caller's
entitled tiers. It must cite them as [doc_id p.N] and say it does not know when they lack the answer.
Code, not the model, abstains first when the best reranker score is below the tuned threshold.
"""

from __future__ import annotations

import re

import anthropic
import yaml
from databricks.sdk import WorkspaceClient

from meridian.common.paths import config_dir
from meridian.common.workspace import bearer_token
from meridian.kb.retrieve import Hit

CONFIG = yaml.safe_load((config_dir() / "agent.yaml").read_text())
ABSTAIN = "I don't have that in the knowledge base."
SYSTEM = f"""You are Meridian Commerce's operations copilot. Answer the question using only the numbered
sources in the user message.
- Cite every fact with its source label in square brackets, for example [DOC-REF-003 p.1] or [SLACK-OPS-004 p.1].
- If the sources do not contain the answer, reply exactly: {ABSTAIN}
- If sources disagree, follow the most recently modified one, say which you followed, and name the older one.
- Be brief: one to three sentences. Do not use outside knowledge, and never guess numbers.
- Do not comment on a source's access tier or restrictions; access is already checked before you see it."""
CITATION = re.compile(r"\[([A-Z][A-Z0-9-]+) p\.(\d+)\]")


def gateway_client(w: WorkspaceClient) -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=f"{w.config.host}/ai-gateway/anthropic", auth_token=bearer_token(w))


def format_sources(hits: list[Hit]) -> str:
    return "\n\n".join(f"[{h.doc_id} p.{h.page}] {h.title} (version {h.source_version or 'n/a'}, modified "
                       f"{(h.modified_at or '')[:10]}, {h.tier} tier)\n{h.text}" for h in hits)


def answer(client: anthropic.Anthropic, question: str, hits: list[Hit], model: str | None = None,
           threshold: float | None = None) -> dict:
    threshold = CONFIG["abstain_below_score"] if threshold is None else threshold
    if not hits or hits[0].score < threshold:
        return {"answer": ABSTAIN, "abstained": True, "abstained_by": "score threshold", "citations": [],
                "usage": None}
    resp = client.messages.create(
        model=model or CONFIG["answer_model"], max_tokens=400,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"Sources:\n\n{format_sources(hits)}\n\nQuestion: {question}"}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    abstained = text.startswith(ABSTAIN)
    return {"answer": text, "abstained": abstained, "abstained_by": "model" if abstained else None,
            "citations": sorted({(d, int(p)) for d, p in CITATION.findall(text)}),
            "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens,
                      "cache_read": getattr(resp.usage, "cache_read_input_tokens", None)}}
