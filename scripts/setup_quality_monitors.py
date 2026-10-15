"""Native Data Quality Monitoring (PREVIEW API) for a target (T05, SM6; idempotent).

1. Table monitor on silver.payments: time-series profiling on created_at (1 hour and 1 day), sliced by
   acquirer_id, with a custom failure_rate metric, so the native drift metrics show the acq_7 shift.
2. Schema monitor on gold with anomaly detection (freshness and completeness across its tables).
Metrics land in the obs schema. Our own drift_check job stays as the independent cross-check.

    uv run --group dbx python scripts/setup_quality_monitors.py --target dev [--refresh]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import dataquality as dq

from meridian.common.bundle import target_names
from meridian.common.workspace import warehouse_id

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "T05"
FAILURE_RATE = dq.DataProfilingCustomMetric(
    name="failure_rate",
    definition="avg(CASE WHEN status = 'failed' THEN 1.0 ELSE 0.0 END)",
    input_columns=[":table"],
    output_data_type="double",
    type=dq.DataProfilingCustomMetricType.DATA_PROFILING_CUSTOM_METRIC_TYPE_AGGREGATE,
)


def existing(w: WorkspaceClient, object_type: str, object_id: str) -> dq.Monitor | None:
    try:
        return w.data_quality.get_monitor(object_type, object_id)
    except Exception:  # noqa: BLE001  not found
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="dev")
    parser.add_argument("--refresh", action="store_true", help="start a refresh of the table monitor")
    args = parser.parse_args()
    names = target_names(args.target)
    w = WorkspaceClient()
    obs = w.schemas.get(f"{names.catalog}.{names.schemas['obs']}")
    gold = w.schemas.get(f"{names.catalog}.{names.schemas['gold']}")
    table = w.tables.get(names.table("silver", "payments"))
    out = {"target": args.target, "ran_at": datetime.now(UTC).isoformat()}

    current = existing(w, "table", table.table_id)
    if current and "FAILED" in str(current.data_profiling_config.status):
        w.data_quality.delete_monitor("table", table.table_id)  # a failed monitor cannot be refreshed
        current = None
    if not current:
        assets_dir = f"/Workspace/Users/{w.current_user.me().user_name}/meridian_monitoring/{args.target}"
        w.workspace.mkdirs(assets_dir)
        w.data_quality.create_monitor(dq.Monitor(object_type="table", object_id=table.table_id,
            data_profiling_config=dq.DataProfilingConfig(
                output_schema_id=obs.schema_id,
                assets_dir=assets_dir,
                time_series=dq.TimeSeriesConfig(timestamp_column="created_at", granularities=[
                    dq.AggregationGranularity.AGGREGATION_GRANULARITY_1_HOUR,
                    dq.AggregationGranularity.AGGREGATION_GRANULARITY_1_DAY]),
                slicing_exprs=["acquirer_id"],
                custom_metrics=[FAILURE_RATE],
                warehouse_id=warehouse_id(w),
                schedule=dq.CronSchedule(quartz_cron_expression="0 0 * * * ?", timezone_id="Asia/Singapore"),
            )))
    monitor = w.data_quality.get_monitor("table", table.table_id)
    cfg = monitor.data_profiling_config
    out["table_monitor"] = {"table": table.full_name, "profile_metrics": cfg.profile_metrics_table_name,
                            "drift_metrics": cfg.drift_metrics_table_name, "dashboard_id": cfg.dashboard_id,
                            "status": str(cfg.status)}
    print("table monitor:", out["table_monitor"])

    if not existing(w, "schema", gold.schema_id):
        w.data_quality.create_monitor(dq.Monitor(object_type="schema", object_id=gold.schema_id,
                                                 anomaly_detection_config=dq.AnomalyDetectionConfig()))
    out["schema_monitor"] = {"schema": gold.full_name, "anomaly_detection": "enabled"}
    print("schema monitor:", out["schema_monitor"])

    if args.refresh:
        refresh = w.data_quality.create_refresh("table", table.table_id, dq.Refresh(object_type="table",
                                                                                   object_id=table.table_id))
        out["refresh_id"] = refresh.refresh_id
        print("refresh started:", refresh.refresh_id)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"quality_monitors_{args.target}.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
