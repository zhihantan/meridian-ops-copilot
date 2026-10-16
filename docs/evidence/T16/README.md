# T16 golden set, retrieval options, abstention (2026-10-16)

20 questions (`config/golden_qa.yaml`): 10 dev, 10 test; 16 answerable (5 need the finance tier), 4 out of scope.
Each runs as the persona its tier needs, through the same retriever and answer step the agent uses. Small
samples: read the counts, not the rates.

Retrieval ablation (`retrieval_summary.json`, `retrieval_dev.csv`, `retrieval_test.csv`), k = 5, answerable questions:

| Variant | Recall@5 dev / test | MRR dev / test | Abstention on test (threshold from dev) |
|---|---|---|---|
| V0 ANN | 0.94 / 0.94 | 0.94 / 0.94 | 0 of 2 out-of-scope abstained |
| V1 hybrid | 1.00 / 1.00 | 0.81 / 0.88 | 1 of 2, plus 2 answerable wrongly abstained |
| V2 hybrid + reranker | 1.00 / 1.00 | 1.00 / 0.94 | 2 of 2, no wrong abstentions |

V2 is the agent's setting (`config/agent.yaml`): the reranker score is a usable abstention signal (threshold 0.5283).

Answers (`answers.json`; `mlflow.genai.evaluate`, answer model `databricks-claude-sonnet-5-5` through Unity Gateway,
judge `databricks-claude-sonnet-4-6`, pinned):

| Metric | dev | test |
|---|---|---|
| Correctness (judge) | 8/8 | 7/8 |
| RetrievalGroundedness (judge) | 7/8 | 8/8 |
| RetrievalSufficiency (judge) | 8/8 | 7/8 |
| Cites an expected document (code) | 8/8 | 8/8 |
| States the key fact verbatim (code; strict substring) | 7/8 | 6/8 |
| Abstains exactly when it should (code) | 10/10 | 10/10 |

Abstention over all 20: 4 of 4 out-of-scope abstained, 0 of 16 in-scope (recall 1.0, precision 1.0; the dev split
tuned the threshold). One prompt rule was added from a dev failure (no commentary on access tiers), which lifted test
groundedness from 6/8 to 8/8. Misses to read: G10 (judge says the two-part answer is incomplete), G04 and G06 (the
answers are right; the key-fact check is a strict substring). `judge_handcheck.md` lists ten dev judge verdicts for a
person to confirm. Query rewriting is not built.
