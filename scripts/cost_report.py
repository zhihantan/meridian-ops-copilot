"""Cost (T27): prompt caching on and off, and what the POC itself has cost, from published list prices.

1. Caching: the token totals of scripts/cache_experiment.py, priced with config/prices.yaml (DBUs per million
   tokens, cited) and the SKU's USD per DBU from system.billing.list_prices. The same calls are then looked up in
   system.ai_gateway.usage (not real-time) as a cross-check.
2. POC cost: system.billing.usage for this workspace since --since, at list price, for what is Meridian's:
   jobs and pipelines tagged project=meridian-poc, the meridian-search AI Search endpoint, the copilot app, and
   model and Genie usage run as Meridian's service principals. The workspace is shared with other projects, so
   the SQL warehouse and the presenter's own model calls are reported separately and not counted.
Writes docs/evidence/T27/cost.json.

    uv run --group dbx python scripts/cost_report.py --since 2026-10-14
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from meridian.common.personas import principal_names
from meridian.common.workspace import sql, warehouse_id

REPO = Path(__file__).resolve().parents[1]
PRICE_JOIN = """LEFT JOIN system.billing.list_prices p ON p.sku_name = u.sku_name AND p.cloud = u.cloud
    AND p.currency_code = 'USD' AND u.usage_start_time >= p.price_start_time
    AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--since", required=True, help="first usage date of the POC, YYYY-MM-DD")
    p.add_argument("--app", default="agent-bricks-meridian-copilot")
    p.add_argument("--endpoint", default="meridian-search")
    args = p.parse_args()
    w = WorkspaceClient()
    ws = str(w.get_workspace_id())
    prices = yaml.safe_load((REPO / "config" / "prices.yaml").read_text())["models"]
    calls = json.loads((REPO / "docs" / "evidence" / "T27" / "cache_calls.json").read_text())
    model = prices[calls["model"]]
    usd_per_dbu = float(sql(w, """SELECT pricing.default FROM system.billing.list_prices WHERE sku_name = :sku
        AND currency_code = 'USD' AND price_end_time IS NULL""", parameters={"sku": model["sku"]})[0][0])

    def usd(tokens: dict) -> float:
        rate = model["dbu_per_million_tokens"]
        return round(sum(tokens.get(k, 0) / 1e6 * rate[k] for k in rate) * usd_per_dbu, 6)

    caching = {mode: {"tokens": {"input": s["input"], "cache_write": s["cache_write"], "cache_read": s["cache_read"],
                                 "output": s["output"]}, "calls": s["calls"], "median_seconds": s["median_seconds"]}
               for mode, s in calls["summary"].items()}
    for c in caching.values():
        c["usd"] = usd(c["tokens"])
    on, off = caching["cache on"]["usd"], caching["cache off"]["usd"]
    since, until = calls["window_utc"]
    g = sql(w, """SELECT count(*), sum(input_tokens), sum(output_tokens), sum(token_details.cache_read_input_tokens),
                         sum(token_details.cache_creation_input_tokens)
                  FROM system.ai_gateway.usage WHERE workspace_id = :ws AND requester = :me AND endpoint_name = :model
                    AND event_time BETWEEN to_timestamp(:since) - INTERVAL 1 MINUTE AND to_timestamp(:until) + INTERVAL 1 MINUTE""",
            parameters={"ws": ws, "me": w.current_user.me().user_name, "model": calls["model"], "since": since,
                        "until": until})[0]
    gateway = {"rows_landed": int(g[0]), "expected": sum(c["calls"] for c in caching.values()),
               "input": int(g[1] or 0), "output": int(g[2] or 0), "cache_read": int(g[3] or 0),
               "cache_write": int(g[4] or 0)}

    names = principal_names(w)
    meridian = [principal for principal, persona in names.items() if persona != "eli"]
    meridian.append(next(sp.application_id for sp in w.service_principals.list(filter='displayName eq "meridian-ci"')))
    meridian.append(w.apps.get(args.app).service_principal_client_id)
    params = {"ws": ws, "since": args.since, "endpoint": args.endpoint, "app": args.app, "wh": warehouse_id(w),
              "me": w.current_user.me().user_name} | {f"m{i}": m for i, m in enumerate(meridian)}
    ids = ", ".join(f":m{i}" for i in range(len(meridian)))
    category = f"""CASE WHEN u.custom_tags['project'] = 'meridian-poc' THEN 'jobs and pipelines tagged project=meridian-poc'
        WHEN u.usage_metadata.endpoint_name = :endpoint THEN 'AI Search endpoint ' || :endpoint
        WHEN u.usage_metadata.app_name = :app THEN 'copilot app compute'
        WHEN u.identity_metadata.run_as IN ({ids}) THEN 'model, Genie and other usage run as Meridian principals'
        WHEN u.usage_metadata.warehouse_id = :wh THEN 'not counted: SQL warehouse, shared with other projects'
        WHEN u.identity_metadata.run_as = :me AND u.billing_origin_product IN ('MODEL_SERVING', 'GENIE', 'AI_GATEWAY')
          THEN 'not counted: the presenter''s own model and Genie calls, all projects' END"""
    rows = sql(w, f"""SELECT {category} AS category, u.billing_origin_product, round(sum(u.usage_quantity), 2),
                             round(sum(u.usage_quantity * p.pricing.default), 2)
                      FROM system.billing.usage u {PRICE_JOIN}
                      WHERE u.workspace_id = :ws AND u.usage_date >= to_date(:since) AND u.usage_unit = 'DBU'
                      GROUP BY 1, 2 HAVING category IS NOT NULL ORDER BY 1, 4 DESC""", parameters=params)
    poc = [{"category": r[0], "product": r[1], "dbu": float(r[2] or 0), "usd_list": float(r[3] or 0)} for r in rows]
    counted = [r for r in poc if not r["category"].startswith("not counted")]
    # An estimate for the shared warehouse: Meridian's share of statement execution time on it.
    share = sql(w, f"""SELECT sum(CASE WHEN executed_by IN ({ids}) OR executed_as IN ({ids})
                                    OR (executed_by = :me AND statement_text ILIKE '%meridian%') THEN execution_duration_ms
                                    ELSE 0 END) / sum(execution_duration_ms)
                       FROM system.query.history WHERE workspace_id = :ws AND compute.warehouse_id = :wh
                         AND start_time >= to_timestamp(:since)""", parameters=params)[0][0]
    warehouse_usd = sum(r["usd_list"] for r in poc if r["category"].startswith("not counted: SQL warehouse"))
    estimate = {"meridian_share_of_execution_time": round(float(share or 0), 3),
                "usd_list": round(float(share or 0) * warehouse_usd, 2),
                "method": "the warehouse's list-price cost times Meridian's share of statement execution time "
                          "(Meridian principals, and the presenter's statements naming a meridian catalog)"}
    latest = sql(w, "SELECT max(usage_date) FROM system.billing.usage WHERE workspace_id = :ws", parameters={"ws": ws})

    result = {
        "task": "T27 cost", "at": datetime.now(UTC).isoformat(),
        "prices": {"model": calls["model"], "dbu_per_million_tokens": model["dbu_per_million_tokens"],
                   "source": model["source"], "read": model["read"], "usd_per_dbu": usd_per_dbu,
                   "usd_per_dbu_source": f"system.billing.list_prices, SKU {model['sku']}",
                   "note": model.get("note")},
        "caching": caching | {"saving_pct": round(100 * (off - on) / off, 1) if off else None,
                              "gateway_usage_cross_check": gateway},
        "poc_cost": {"since": args.since, "billing_data_through": latest[0][0], "rows": poc,
                     "counted_usd_list": round(sum(r["usd_list"] for r in counted), 2),
                     "counted_dbu": round(sum(r["dbu"] for r in counted), 2),
                     "shared_warehouse_estimate": estimate},
    }
    out = REPO / "docs" / "evidence" / "T27" / "cost.json"
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps({"caching_usd": {m: c["usd"] for m, c in caching.items()}, "saving_pct": result["caching"]["saving_pct"],
                      "gateway": gateway}, indent=1))
    for r in poc:
        print(f"  {r['category'][:62]:<62} {r['product']:<16} {r['dbu']:>10} DBU  ${r['usd_list']}")
    print("counted:", result["poc_cost"]["counted_usd_list"], "USD at list price, through", latest[0][0],
          "| shared warehouse, estimated Meridian share:", estimate)


if __name__ == "__main__":
    main()
