"""SM3: AI Search Delta Sync index on a 5-row table (PREVIEW client `databricks-ai-search`).

Runs ANN, hybrid and hybrid plus reranker queries, then deletes a source row and checks that it
leaves the index. Uses a throwaway schema; pass --cleanup to drop it afterwards.

    uv run --group agent --group dbx python scripts/smoke/sm3_ai_search.py --schema <catalog>.meridian_smoke
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from databricks.ai_search.client import AISearchClient
from databricks.ai_search.reranker import DatabricksReranker
from databricks.sdk import WorkspaceClient

from meridian.common.workspace import bearer_token, sql

ENDPOINT = "meridian-search"
EMBEDDING_ENDPOINT = "databricks-gte-large-en"
EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "SM3"
ROWS = [
    (1, "Refunds above SGD 500 need approval from a second person before payout."),
    (2, "acq_7 is a domestic acquirer that only processes SGD payments."),
    (3, "Page the payments on-call engineer when an acquirer outage lasts over 30 minutes."),
    (4, "Payment logs are retained for seven years for audit purposes."),
    (5, "CANARY-SM3 this row is deleted during the smoke test."),
]


def ids(result: dict) -> list[int]:
    return [int(r[0]) for r in result.get("result", {}).get("data_array", [])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", required=True, help="catalog.schema for the throwaway table and index")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    table, index_name = f"{args.schema}.sm3_docs", f"{args.schema}.sm3_docs_idx"

    w = WorkspaceClient()
    sql(w, f"CREATE SCHEMA IF NOT EXISTS {args.schema}")
    sql(w, f"CREATE OR REPLACE TABLE {table} (id INT, text STRING) TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    values = ", ".join(f"({i}, '{t}')" for i, t in ROWS)
    sql(w, f"INSERT INTO {table} VALUES {values}")

    client = AISearchClient(workspace_url=w.config.host, personal_access_token=bearer_token(w), disable_notice=True)
    if client.index_exists(ENDPOINT, index_name):
        client.delete_index(ENDPOINT, index_name)
        time.sleep(10)
    started = time.time()
    index = client.create_delta_sync_index_and_wait(
        endpoint_name=ENDPOINT, index_name=index_name, primary_key="id", source_table_name=table,
        pipeline_type="TRIGGERED", embedding_source_column="text", embedding_model_endpoint_name=EMBEDDING_ENDPOINT,
    )
    created_s = round(time.time() - started)

    index.wait_until_ready(wait_for_updates=True, timeout=timedelta(minutes=15))
    query = "who has to approve a large refund"
    results = {}
    for name, kwargs in {
        "ann": {"query_type": "ANN"},
        "hybrid": {"query_type": "HYBRID"},
        "hybrid_rerank": {"query_type": "HYBRID", "reranker": DatabricksReranker(columns_to_rerank=["text"])},
    }.items():
        for attempt in range(4):  # a freshly recreated index can briefly point at the old pipeline
            try:
                results[name] = ids(index.similarity_search(columns=["id", "text"], query_text=query,
                                                            num_results=3, **kwargs))
                break
            except Exception as exc:  # noqa: BLE001  record failures instead of stopping
                results[name] = f"error: {exc}"[:300]
                time.sleep(15)
        print(name, results[name])

    # The initial build may still be running after create returns; sync only once it has finished.
    index.wait_until_ready(wait_for_updates=True, timeout=timedelta(minutes=15))
    sql(w, f"DELETE FROM {table} WHERE id = 5")
    started = time.time()
    for _ in range(30):
        try:
            index.sync()
            break
        except Exception as exc:
            if "not ready to sync" not in str(exc):
                raise
            time.sleep(10)
    index.wait_until_ready(wait_for_updates=True, timeout=timedelta(minutes=15))
    canary = ids(index.similarity_search(columns=["id", "text"], query_text="CANARY-SM3", num_results=5, query_type="HYBRID"))
    delete_s = round(time.time() - started)
    print("after delete:", canary, f"({delete_s}s)")

    status = "PASS" if (isinstance(results["hybrid"], list) and results["hybrid"][:1] == [1] and 5 not in canary) else "FAIL"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "result.json").write_text(json.dumps({
        "test": "SM3 AI Search delta sync index", "ran_at": datetime.now(UTC).isoformat(), "endpoint": ENDPOINT,
        "embedding_endpoint": EMBEDDING_ENDPOINT, "index_create_seconds": created_s, "query": query,
        "top3_ids": results, "delete_propagation_seconds": delete_s, "canary_results_after_delete": canary,
        "reranker_status": "ok" if isinstance(results["hybrid_rerank"], list) else "failed", "status": status,
    }, indent=2))
    print(status)
    if args.cleanup:
        client.delete_index(ENDPOINT, index_name)
        sql(w, f"DROP SCHEMA IF EXISTS {args.schema} CASCADE")


if __name__ == "__main__":
    main()
