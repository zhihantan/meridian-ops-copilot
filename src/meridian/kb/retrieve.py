"""Entitlement-aware retrieval (T16, T17, BUILD): which tier indexes a caller may search is decided here.

The caller's groups come from their own verified identity (SCIM Me), and knowledge_tiers in
config/scenario.yaml maps groups to tiers, so a support agent never searches the finance index. Each
entitled index is then queried with the caller's own credentials, so Unity Catalog grants on the index
apply too: two layers, and neither is the model's judgment. If the index refuses (the group list can
briefly lag a membership change that Unity Catalog already enforces, observed in T19), that tier is
dropped for the call, not raised. Hits from several indexes merge by score.

Variants for the ablation: V0 ANN, V1 hybrid, V2 hybrid with the Databricks reranker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from databricks.ai_search.client import AISearchClient
from databricks.ai_search.exceptions import PermissionDenied
from databricks.ai_search.reranker import DatabricksReranker
from databricks.sdk import WorkspaceClient

from meridian.common.paths import config_dir
from meridian.common.workspace import bearer_token

COLUMNS = ["chunk_id", "doc_id", "title", "page", "text", "tier", "source_version", "uri", "modified_at"]
VARIANTS = {"V0": {"query_type": "ANN"}, "V1": {"query_type": "HYBRID"}, "V2": {"query_type": "HYBRID", "rerank": True}}


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    page: int
    text: str
    tier: str
    source_version: str | None
    uri: str
    modified_at: str | None
    score: float


def tier_groups(path: Path | None = None) -> dict[str, list[str]]:
    return yaml.safe_load((path or config_dir() / "scenario.yaml").read_text())["knowledge_tiers"]


def entitled_tiers(groups: set[str], tiers: dict[str, list[str]] | None = None) -> list[str]:
    tiers = tiers or tier_groups()
    return [tier for tier, allowed in tiers.items() if groups & set(allowed)]


def caller_groups(w: WorkspaceClient) -> set[str]:
    me = w.current_user.me()
    return {g.display for g in (me.groups or []) if g.display}


class Retriever:
    """One caller's retriever: entitlements resolved once from the caller's identity."""

    def __init__(self, w: WorkspaceClient, kb_schema: str, endpoint: str = "meridian-search"):
        self.groups = caller_groups(w)
        self.tiers = entitled_tiers(self.groups)
        self.kb_schema, self.endpoint = kb_schema, endpoint
        self.refused: set[str] = set()  # tiers whose index refused this caller
        self.client = AISearchClient(workspace_url=w.config.host, personal_access_token=bearer_token(w),
                                     disable_notice=True)
        self._indexes = {}

    def index(self, tier: str):
        if tier not in self._indexes:
            self._indexes[tier] = self.client.get_index(self.endpoint, f"{self.kb_schema}.idx_{tier}")
        return self._indexes[tier]

    def search(self, query: str, variant: str = "V1", k: int = 5, only: list[str] | None = None) -> list[Hit]:
        """Top k hits over the caller's entitled indexes (narrowed to `only`, if given). ANN similarity and
        reranker scores compare across indexes; hybrid scores are normalized per index, so hybrid lists merge
        by reciprocal rank."""
        spec = VARIANTS[variant]
        per_tier: list[list[Hit]] = []
        for tier in [t for t in self.tiers if only is None or t in only]:  # never an index the caller lacks
            kwargs = {"query_type": spec["query_type"], "disable_notice": True}
            if spec.get("rerank"):
                kwargs["reranker"] = DatabricksReranker(columns_to_rerank=["text"])
            try:
                res = self.index(tier).similarity_search(columns=COLUMNS, query_text=query, num_results=k, **kwargs)
            except PermissionDenied:
                self.refused.add(tier)
                continue
            names = [c["name"] for c in res.get("manifest", {}).get("columns", [])]
            per_tier.append([self._hit(dict(zip(names, row))) for row in res.get("result", {}).get("data_array") or []])
        if spec["query_type"] == "HYBRID" and not spec.get("rerank") and len(per_tier) > 1:
            fused = {}
            for hits in per_tier:
                for rank, h in enumerate(hits):
                    fused[h.chunk_id] = (fused.get(h.chunk_id, (0.0, h))[0] + 1 / (60 + rank), h)
            return [h for _, h in sorted(fused.values(), key=lambda x: x[0], reverse=True)][:k]
        merged = [h for hits in per_tier for h in hits]
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:k]

    @staticmethod
    def _hit(r: dict) -> Hit:
        return Hit(r["chunk_id"], r["doc_id"], r["title"], int(r["page"] or 1), r["text"], r["tier"],
                   r.get("source_version"), r["uri"], r.get("modified_at"), float(r.get("score") or 0))
