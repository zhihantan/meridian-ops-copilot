"""Citation parsing for copilot answers (T16), offline."""

import pytest

pytest.importorskip("anthropic")

from meridian.agent.answer import ABSTAIN, CITATION, format_sources
from meridian.kb.retrieve import Hit


def test_citations_are_parsed():
    text = "Approval is needed above SGD 500 [DOC-RB-021 p.1], posted in #refund-approvals [SLACK-OPS-005 p.1]."
    assert sorted(CITATION.findall(text)) == [("DOC-RB-021", "1"), ("SLACK-OPS-005", "1")]


def test_sources_carry_label_version_and_date():
    hit = Hit("c1", "DOC-RB-021", "Refund approval", 1, "Refunds above SGD 500 ...", "general", "1",
              "u", "2026-08-26T07:00:00", 0.9)
    assert format_sources([hit]).startswith("[DOC-RB-021 p.1] Refund approval (version 1, modified 2026-08-26")
    assert ABSTAIN.endswith("knowledge base.")
