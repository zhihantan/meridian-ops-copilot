"""Retrieval ablation and abstention threshold on the golden set (T16).

Each question runs as the persona its tier needs (finance questions as Ben, the rest as Ava), through the
same entitlement-aware retriever the agent uses, for V0 ANN, V1 hybrid and V2 hybrid with the reranker.
Metrics per variant: recall@5 and MRR over expected documents (answerable questions). Abstention: abstain
when the top score is below a threshold tuned on the dev split (out-of-scope vs answerable), then measured
on the test split. Writes docs/evidence/T16/retrieval_<split>.csv and retrieval_summary.json.

    uv run --group dbx --group agent python scripts/eval_retrieval.py --target prod
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.kb.retrieve import VARIANTS, Retriever

REPO = Path(__file__).resolve().parents[1]
PERSONA = {"finance": "meridian-ben", "general": "meridian-ava"}


def distinct_docs(hits) -> list[str]:
    seen: list[str] = []
    for h in hits:
        if h.doc_id not in seen:
            seen.append(h.doc_id)
    return seen


def abstention(rows: list[dict], variant: str, threshold: float) -> dict:
    """Positive class: out-of-scope questions (the system should abstain)."""
    sub = [r for r in rows if r["variant"] == variant]
    tp = sum(1 for r in sub if not r["answerable"] and r["top_score"] < threshold)
    fp = sum(1 for r in sub if r["answerable"] and r["top_score"] < threshold)
    fn = sum(1 for r in sub if not r["answerable"] and r["top_score"] >= threshold)
    return {"threshold": threshold, "abstained_oos": tp, "abstained_answerable": fp, "answered_oos": fn,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None}


def tune(rows: list[dict], variant: str) -> float:
    """Threshold that best separates out-of-scope from answerable on dev: fewest errors, then the lowest."""
    scores = sorted({r["top_score"] for r in rows if r["variant"] == variant})
    candidates = [(a + b) / 2 for a, b in pairwise(scores)] or scores
    def errors(t):
        a = abstention(rows, variant, t)
        return a["abstained_answerable"] + a["answered_oos"]
    return round(min(candidates, key=lambda t: (errors(t), t)), 4)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    args = p.parse_args()
    t = target_names(args.target)
    kb = f"{t.catalog}.{t.schemas['kb']}"
    questions = yaml.safe_load((REPO / "config" / "golden_qa.yaml").read_text())["questions"]
    retrievers = {tier: Retriever(WorkspaceClient(profile=profile), kb) for tier, profile in PERSONA.items()}

    rows = []
    for q in questions:
        r = retrievers[q["tier_required"]]
        for variant in VARIANTS:
            hits = r.search(q["question"], variant, k=5)
            docs = distinct_docs(hits)
            expected = q["expected_doc_ids"]
            found = [d for d in expected if d in docs]
            first = min((docs.index(d) + 1 for d in found), default=None)
            rows.append({"id": q["id"], "split": q["split"], "type": q["type"], "tier": q["tier_required"],
                         "answerable": q["answerable"], "variant": variant,
                         "recall_at_5": round(len(found) / len(expected), 3) if expected else None,
                         "rr": round(1 / first, 3) if first else 0.0 if expected else None,
                         "top_score": round(hits[0].score, 4) if hits else 0.0, "top_docs": " ".join(docs)})
        print(q["id"], {v: next(x["top_docs"] for x in rows if x["id"] == q["id"] and x["variant"] == v).split()[:3]
                        for v in VARIANTS})

    evidence = REPO / "docs" / "evidence" / "T16"
    evidence.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "test"):
        with (evidence / f"retrieval_{split}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(r for r in rows if r["split"] == split)

    summary = {"task": "T16 retrieval ablation", "target": args.target, "at": datetime.now(UTC).isoformat(),
               "k": 5, "variants": {}}
    for variant in VARIANTS:
        per_split = {}
        for split in ("dev", "test"):
            ans = [r for r in rows if r["variant"] == variant and r["split"] == split and r["answerable"]]
            per_split[split] = {"questions": len(ans),
                                "recall_at_5": round(sum(r["recall_at_5"] for r in ans) / len(ans), 3),
                                "mrr": round(sum(r["rr"] for r in ans) / len(ans), 3)}
        threshold = tune([r for r in rows if r["split"] == "dev"], variant)
        per_split["abstention_test"] = abstention([r for r in rows if r["split"] == "test"], variant, threshold)
        summary["variants"][variant] = per_split
    (evidence / "retrieval_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["variants"], indent=1))


if __name__ == "__main__":
    main()
