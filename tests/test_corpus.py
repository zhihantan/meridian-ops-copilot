"""Tests for the synthetic knowledge corpus (T10) and its question sets (T16 golden set, T19 leakage)."""

import csv
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest
import yaml

pytest.importorskip("reportlab")
pytest.importorskip("docx")

from meridian.synth import corpus

REPO = Path(__file__).resolve().parents[1]
ANCHOR = "2026-10-22T07:00:00+00:00"


def _config(name: str) -> dict:
    return yaml.safe_load((REPO / "config" / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    path = tmp_path_factory.mktemp("corpus")
    corpus.main(["--out", str(path), "--anchor", ANCHOR])
    return path


@pytest.fixture(scope="module")
def manifest(out):
    with (out / "knowledge" / "manifest.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def texts(out, manifest):
    return {row["doc_id"]: (out / "knowledge_text" / f"{Path(row['path']).name}.txt").read_text(encoding="utf-8")
            for row in manifest}


@pytest.fixture(scope="module")
def slack(out):
    return json.loads((out / "slack_export" / "ops-incidents.json").read_text(encoding="utf-8"))


def test_eight_documents_and_slack_export(manifest, slack):
    formats = Counter(row["format"] for row in manifest)
    assert len(manifest) == 8
    assert formats["pdf"] == 3 and formats["docx"] == 2 and formats["md"] + formats["txt"] == 3
    assert len(slack["messages"]) == 25
    assert len({m["msg_key"] for m in slack["messages"]}) == 25


def test_manifest_matches_files(out, manifest):
    on_disk = {p.name for p in (out / "knowledge").iterdir() if p.name != "manifest.csv"}
    assert on_disk == {Path(row["path"]).name for row in manifest}
    for row in manifest:
        assert (out / row["path"]).stat().st_size > 0


def test_expected_facts_in_sidecars(manifest, texts):
    for row in manifest:
        for fact in row["expected_facts"].split(" | "):
            assert fact in texts[row["doc_id"]], (row["doc_id"], fact)


def test_finance_facts_only_in_finance_docs(manifest, texts, slack):
    finance_facts = {cell for cells in corpus.FEE_TABLE.values() for cell in cells}
    finance_facts |= set(corpus.MONTHLY_MINIMUM.values())
    for row in manifest:
        if row["tier"] == "finance":
            finance_facts |= set(row["expected_facts"].split(" | "))
    for q in _config("leakage_questions.yaml")["questions"]:
        finance_facts |= set(q["forbidden_facts"])

    general = {row["doc_id"]: texts[row["doc_id"]] for row in manifest if row["tier"] == "general"}
    general |= {f"SLACK-{m['msg_key']}": m["text"] for m in slack["messages"]}
    leaks = [(fact, source) for fact in finance_facts for source, text in general.items() if fact in text]
    assert not leaks


def test_documents_show_doc_id_and_version(out, manifest):
    for row in manifest:
        path = out / row["path"]
        marker = f"{row['doc_id']} v{row['version']}"
        if row["format"] == "pdf":
            assert marker.encode() in path.read_bytes()
        elif row["format"] == "docx":
            with zipfile.ZipFile(path) as z:
                parts = [z.read(n).decode() for n in z.namelist() if re.match(r"word/(header|footer)\d*\.xml", n)]
            assert any(row["doc_id"] in part for part in parts)
        else:
            assert marker in path.read_text(encoding="utf-8")


def test_fee_schedule_spans_two_pages(out):
    pdf = (out / "knowledge" / "DOC-FEE-001.pdf").read_bytes()
    assert len(re.findall(rb"/Type\s*/Page(?!s)", pdf)) >= 2


def test_golden_set_stratified(manifest, slack):
    questions = _config("golden_qa.yaml")["questions"]
    types = Counter(q["type"] for q in questions)
    assert types == {"single_source": 8, "multi_hop": 2, "numeric": 2, "conflict": 1, "out_of_scope": 4,
                     "finance": 3}
    assert Counter(q["split"] for q in questions) == {"dev": 10, "test": 10}
    for qtype, count in types.items():
        if count >= 2:
            assert {q["split"] for q in questions if q["type"] == qtype} == {"dev", "test"}, qtype
    assert len({q["id"] for q in questions}) == 20
    assert sum(q.get("trap") == "world_knowledge" for q in questions) == 2

    tiers = {row["doc_id"]: row["tier"] for row in manifest}
    known = set(tiers) | {f"SLACK-{m['msg_key']}" for m in slack["messages"]}
    for q in questions:
        if q["type"] == "out_of_scope":
            assert q["answerable"] is False and q["expected_doc_ids"] == []
        else:
            assert q["answerable"] is True and set(q["expected_doc_ids"]) <= known, q["id"]
        needs_finance = any(tiers.get(d) == "finance" for d in q["expected_doc_ids"])
        assert (q["tier_required"] == "finance") == needs_finance, q["id"]


def test_golden_key_facts_in_expected_sources(texts, slack):
    sources = dict(texts) | {f"SLACK-{m['msg_key']}": m["text"] for m in slack["messages"]}
    for q in _config("golden_qa.yaml")["questions"]:
        if q["answerable"]:
            assert any(q["key_fact"] in sources[d] for d in q["expected_doc_ids"]), q["id"]


def test_leakage_questions_are_finance_only_and_distinct(texts):
    questions = _config("leakage_questions.yaml")["questions"]
    golden = {q["question"] for q in _config("golden_qa.yaml")["questions"]}
    assert len(questions) == 6
    for q in questions:
        assert q["question"] not in golden
        for fact in q["forbidden_facts"]:
            assert fact in texts["DOC-FEE-001"], (q["id"], fact)


def test_workflows_match_spec_and_scenario():
    scenario = _config("scenario.yaml")
    v3, v4 = _config("workflows/rb014_v3.yaml"), _config("workflows/rb014_v4.yaml")
    assert v3["status"] == "approved" and v3["approved_by"] and v3["approved_by"] != v3["owner"]
    assert v4["status"] == "draft" and v4["approved_by"] is None
    assert [s["id"] for s in v3["steps"]] == ["s1", "s2", "s3", "s4", "s5", "s6"]
    assert [s["tool"] for s in v3["steps"]] == ["ask_genie", "search_kb", "compute_impact", "propose_refund",
                                               "request_approval", "refund_batch"]
    assert len(v4["steps"]) > len(v3["steps"])
    for wf in (v3, v4):
        assert wf["params"]["refund_approval_threshold_sgd"] == scenario["policy"]["refund_approval_threshold_sgd"]
        assert wf["params"]["refundable_failure_codes"] == scenario["policy"]["refundable_failure_codes"]
    s2 = v3["steps"][1]
    assert s2["tier"] == "finance" and s2["next"]["if_not_entitled"] == "escalate_to_finance"


def test_generator_is_deterministic(out, tmp_path):
    again = tmp_path / "again"
    corpus.main(["--out", str(again), "--anchor", ANCHOR])
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = path.relative_to(out)
        assert (again / rel).read_bytes() == path.read_bytes(), rel
