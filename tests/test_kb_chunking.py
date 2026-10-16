"""Knowledge chunking (T12), offline."""

from meridian.kb.chunking import MAX_CHARS, chunk_id, chunk_parsed, chunk_text, table_to_text

PARSED = {"document": {"elements": [
    {"type": "page_header", "content": "Meridian Commerce · DOC-X · v4", "bbox": [{"page_id": 0}]},
    {"type": "title", "content": "Fee schedule", "bbox": [{"page_id": 0}]},
    {"type": "section_header", "content": "SLA", "bbox": [{"page_id": 0}]},
    {"type": "text", "content": "Failure rate above 5% over 6 hours earns a credit.", "bbox": [{"page_id": 0}]},
    {"type": "table", "content": "<table><tr><th>acq</th><th>rate</th></tr><tr><td>acq_7</td><td>1.79%</td></tr></table>",
     "bbox": [{"page_id": 1}]},
    {"type": "page_footer", "content": "Page 2", "bbox": [{"page_id": 1}]},
]}}


def test_parsed_chunks_keep_pages_and_drop_boilerplate():
    chunks = chunk_parsed("DOC-X Fee schedule", PARSED)
    assert [c.page for c in chunks] == [1, 2]
    assert "Meridian Commerce" not in chunks[0].text and "Page 2" not in chunks[1].text
    assert chunks[0].text.startswith("DOC-X Fee schedule") and "Failure rate above 5%" in chunks[0].text
    assert "acq_7 | 1.79%" in chunks[1].text


def test_table_to_text():
    assert table_to_text("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>") == "a | b\nc | d"


def test_long_text_splits_under_the_limit():
    text = "# Policy\n\n" + " ".join(f"Sentence {i} is here." for i in range(600))
    chunks = chunk_text("Policy doc", text)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS + 100 for c in chunks)  # heading line plus the body limit
    assert all(c.text.startswith("Policy doc — Policy") for c in chunks)


def test_chunk_ids_are_stable_and_change_with_content():
    assert chunk_id("DOC-1", "abc", 0) == chunk_id("DOC-1", "abc", 0)
    assert chunk_id("DOC-1", "abc", 0) != chunk_id("DOC-1", "abd", 0)


def test_title_element_equal_to_the_document_title_is_not_repeated():
    parsed = {"document": {"elements": [{"type": "title", "content": "Fee schedule", "bbox": [{"page_id": 0}]},
                                        {"type": "text", "content": "Body.", "bbox": [{"page_id": 0}]}]}}
    assert chunk_parsed("Fee schedule", parsed)[0].text == "Fee schedule\nBody."
