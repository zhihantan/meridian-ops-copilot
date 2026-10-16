"""Answer quality and abstention on the golden set (T16): MLflow judges over traced copilot answers.

Each question runs as the persona its tier needs (finance questions as Ben, the rest as Ava) through the
retriever and answer step the agent uses (config/agent.yaml). mlflow.genai.evaluate scores Correctness,
RetrievalGroundedness and RetrievalSufficiency with the pinned judge model, plus code checks: abstained
exactly when it should, cited an expected document, stated the key fact. Traces and assessments land in
an MLflow experiment; per-question results in docs/evidence/T16/answers.json, ten judge rationales from the
dev split in docs/evidence/T16/judge_handcheck.md.

    uv run --group dbx --group agent python scripts/eval_answers.py --target prod
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import mlflow
import yaml
from databricks.sdk import WorkspaceClient
from mlflow.entities import Document, SpanType
from mlflow.genai.scorers import Correctness, RetrievalGroundedness, RetrievalSufficiency, scorer

from meridian.agent.answer import ABSTAIN, CONFIG, answer, gateway_client
from meridian.common.bundle import target_names
from meridian.common.workspace import bearer_token
from meridian.kb.retrieve import Retriever

REPO = Path(__file__).resolve().parents[1]
PERSONA = {"finance": "meridian-ben", "general": "meridian-ava"}


@scorer
def abstention(outputs, expectations) -> bool:
    """True when the copilot abstained exactly on the questions the knowledge base cannot answer."""
    return outputs.strip().startswith(ABSTAIN) == (not expectations["answerable"])


@scorer
def cites_expected_doc(outputs, expectations):
    if not expectations["answerable"]:
        return None
    return any(f"[{doc}" in outputs for doc in expectations["expected_doc_ids"])


@scorer
def states_key_fact(outputs, expectations):
    if not expectations["answerable"]:
        return None
    return expectations["key_fact"].lower() in outputs.lower()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    p.add_argument("--experiment", default="meridian-eval")
    args = p.parse_args()
    t = target_names(args.target)
    kb = f"{t.catalog}.{t.schemas['kb']}"
    w = WorkspaceClient()
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(f"/Users/{w.current_user.me().user_name}/{args.experiment}")
    retrievers = {tier: Retriever(WorkspaceClient(profile=profile), kb) for tier, profile in PERSONA.items()}
    client = gateway_client(w)
    hits_by_question: dict[str, list] = {}

    @mlflow.trace(span_type=SpanType.RETRIEVER)
    def retrieve(question: str, tier: str) -> list[Document]:
        hits = retrievers[tier].search(question, CONFIG["retrieval_variant"], CONFIG["top_k"])
        hits_by_question[question] = hits
        return [Document(page_content=h.text, metadata={"doc_uri": h.doc_id, "chunk_id": h.chunk_id,
                                                        "page": h.page, "score": h.score}) for h in hits]

    @mlflow.trace  # one trace per question, with the retriever span inside it
    def predict(question: str, tier: str) -> str:
        retrieve(question, tier)
        return answer(client, question, hits_by_question[question])["answer"]

    questions = yaml.safe_load((REPO / "config" / "golden_qa.yaml").read_text())["questions"]
    data = [{"inputs": {"question": q["question"], "tier": q["tier_required"]},
             "expectations": {"reference_answer": q["expected_answer"],   # the judge takes facts or a response, not both
                              "expected_facts": [q["key_fact"]] if q["answerable"]
                              else ["The assistant says the knowledge base does not have the answer."],
                              "answerable": q["answerable"], "expected_doc_ids": q["expected_doc_ids"],
                              "key_fact": q.get("key_fact") or "", "id": q["id"], "split": q["split"]}}
            for q in questions]
    judge = f"databricks:/{CONFIG['judge_model']}"
    # MLflow's worker threads each build their own Databricks client; many concurrent CLI token lookups
    # fail on the OS keyring, so hand them one short-lived token for this run (personas already hold theirs).
    os.environ.update({"DATABRICKS_HOST": w.config.host, "DATABRICKS_TOKEN": bearer_token(w),
                       "MLFLOW_GENAI_EVAL_MAX_WORKERS": "4"})
    os.environ.pop("DATABRICKS_CONFIG_PROFILE", None)
    result = mlflow.genai.evaluate(
        data=data, predict_fn=predict,
        scorers=[Correctness(model=judge), RetrievalGroundedness(model=judge), RetrievalSufficiency(model=judge),
                 abstention, cites_expected_doc, states_key_fact])

    df = result.result_df
    scores = ("correctness", "retrieval_groundedness", "retrieval_sufficiency", "abstention", "cites_expected_doc",
              "states_key_fact")
    rows = []
    for _, r in df.iterrows():  # expectations come back flattened as <name>/value columns
        response = r["response"]
        if isinstance(response, str) and response.startswith('"'):  # JSON-encoded string
            response = json.loads(response)
        row = {"id": r["id/value"], "split": r["split/value"], "answerable": bool(r["answerable/value"]),
               "answer": str(response)}
        for name in scores:
            row[name] = r.get(f"{name}/value")
            err = r.get(f"{name}/error_message")
            if isinstance(err, str) and err:
                row[f"{name}_error"] = err[:200]
                print(f"{row['id']} {name} error: {err[:160]}")
        rows.append(row)
    rows.sort(key=lambda x: x["id"])

    def rate(name: str, split: str, only_answerable: bool = True) -> str:
        vals = [r.get(name) for r in rows if r["split"] == split and (r["answerable"] or not only_answerable)]
        vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]  # NaN: not scored
        ok = sum(1 for v in vals if v in (True, "yes"))
        return f"{ok}/{len(vals)}"

    oos = [r for r in rows if not r["answerable"]]
    ans = [r for r in rows if r["answerable"]]

    def abstained(r: dict) -> bool:
        return r["answer"].strip().startswith(ABSTAIN)

    summary = {
        "task": "T16 answers", "target": args.target, "at": datetime.now(UTC).isoformat(),
        "answer_model": CONFIG["answer_model"], "judge_model": CONFIG["judge_model"],
        "retrieval_variant": CONFIG["retrieval_variant"], "experiment_run_id": result.run_id,
        "by_split": {split: {name: rate(name, split) for name in
                             ("correctness", "retrieval_groundedness", "retrieval_sufficiency",
                              "cites_expected_doc", "states_key_fact")} | {"abstention": rate("abstention", split, False)}
                     for split in ("dev", "test")},
        "abstention_all_20": {"out_of_scope_abstained": f"{sum(map(abstained, oos))}/{len(oos)}",
                              "in_scope_abstained": f"{sum(map(abstained, ans))}/{len(ans)}",
                              "recall": round(sum(map(abstained, oos)) / len(oos), 3),
                              "precision": round(sum(map(abstained, oos)) / max(1, sum(map(abstained, rows))), 3)},
        "rows": rows,
    }
    evidence = REPO / "docs" / "evidence" / "T16"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "answers.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")

    lines = ["# Judge hand-check (T16)", "",
             f"Ten judge verdicts from the dev split (judge `{CONFIG['judge_model']}`), for a person to confirm.", "",
             "| Question | Judge | Verdict | Rationale (start) |", "|---|---|---|---|"]
    for _, r in df.iterrows():
        if r["split/value"] != "dev" or len(lines) >= 16:
            continue
        rationale = str(r.get("correctness/rationale", "")).replace("\n", " ").replace("|", "/")[:180]
        lines.append(f"| {r['id/value']} | correctness | {r.get('correctness/value')} | {rationale} |")
    (evidence / "judge_handcheck.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
