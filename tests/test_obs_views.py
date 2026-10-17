"""The observability SQL file parses into complete statements for a target (T06b), offline."""

from pathlib import Path

from meridian.common.sqlfile import statements

SQL = Path(__file__).resolve().parents[1] / "sql" / "obs_views.sql"
VALUES = {"catalog": "meridian", "target": "prod", "workspace_id": "123", "obs": "meridian.obs",
          "gov": "meridian.gov", "quarantine": "meridian.quarantine", "kb": "meridian.kb"}


def test_every_placeholder_is_filled():
    parsed = statements(str(SQL), VALUES)
    assert parsed and all("${" not in s and not s.endswith(";") for s in parsed)


def test_one_statement_per_view():
    views = [s.split()[4] for s in statements(str(SQL), VALUES)]
    assert views == [f"meridian.obs.{v}" for v in ("v_job_runs", "v_task_runs", "v_pipeline_events",
                                                    "v_expectation_metrics", "v_query_history", "v_audit",
                                                    "v_pipeline_health")]


def test_kb_views_are_separate():  # staging has no knowledge base, so its views job must not need one
    parsed = statements(str(SQL.with_name("kb_views.sql")), VALUES)
    assert [s.split()[4] for s in parsed] == ["meridian.obs.v_kb_changes"]
    assert not any("meridian.kb." in s for s in statements(str(SQL), VALUES))


def test_procedures_stay_whole():
    sql = Path(__file__).resolve().parents[1] / "sql" / "workflow_objects.sql"
    parsed = statements(str(sql), {"agent": "c.agent", "kb": "c.kb", "silver": "c.silver", "refund_threshold": "500"})
    procedures = [s for s in parsed if s.upper().startswith("CREATE OR REPLACE PROCEDURE")]
    text = sql.read_text()
    assert len(procedures) == text.count("CREATE OR REPLACE PROCEDURE") == 11
    assert all(p.rstrip().upper().endswith("END") and "BEGIN" in p for p in procedures)
    assert len(parsed) == text.count("CREATE TABLE") + text.count("CREATE OR REPLACE VIEW") + len(procedures)
