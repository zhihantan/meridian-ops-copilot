"""Chunking for the knowledge base (T12, BUILD): parsed documents and plain text to retrieval chunks.

Chunks are about 500 tokens (about 2,000 characters), never span pages, and start with the document
title and the current section heading, so a chunk read on its own still says where it came from.
Chunk IDs are a hash of the document, its content hash and the chunk's position: unchanged documents
keep their IDs across runs, and an edited document gets new ones (the old ones are deleted).
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass

MAX_CHARS = 2000
SKIP_TYPES = {"page_header", "page_footer", "page_number"}


@dataclass(frozen=True)
class Chunk:
    page: int
    seq: int
    text: str


def chunk_id(doc_id: str, content_hash: str, seq: int) -> str:
    return hashlib.sha256(f"{doc_id}:{content_hash}:{seq}".encode()).hexdigest()[:32]


def table_to_text(markup: str) -> str:
    """HTML table from ai_parse_document to pipe-separated rows."""
    text = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " | ", markup, flags=re.IGNORECASE)
    text = re.sub(r"</tr>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return "\n".join(line.strip() for line in html.unescape(text).splitlines() if line.strip())


def _split(text: str) -> list[str]:
    """An element longer than a chunk, cut at sentence or line boundaries."""
    parts = []
    while len(text) > MAX_CHARS:
        cut = max(text.rfind(". ", 0, MAX_CHARS), text.rfind("\n", 0, MAX_CHARS))
        cut = cut + 1 if cut > MAX_CHARS // 2 else MAX_CHARS
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    return [*parts, text] if text else parts


def _pack(title: str, pieces: list[tuple[int, str, str]]) -> list[Chunk]:
    """pieces: (page, section, text) in reading order, packed greedily per page up to MAX_CHARS."""
    chunks: list[Chunk] = []
    buf: list[str] = []
    size, page, section = 0, 1, ""

    def flush() -> None:
        nonlocal size
        if buf:
            head = title if not section or section == title else f"{title} — {section}"
            chunks.append(Chunk(page=page, seq=len(chunks), text=head + "\n" + "\n".join(buf)))
        buf.clear()
        size = 0

    for p, sec, text in pieces:
        for part in _split(text):
            if buf and (p != page or size + len(part) > MAX_CHARS):
                flush()
            if not buf:  # a chunk is labelled with the page and section it starts in
                page, section = p, sec
            buf.append(part)
            size += len(part)
    flush()
    return chunks


def chunk_parsed(title: str, parsed: dict) -> list[Chunk]:
    """Chunks from ai_parse_document output (format version 2.0: document.elements with page IDs)."""
    pieces: list[tuple[int, str, str]] = []
    section = ""
    for el in parsed.get("document", {}).get("elements", []):
        kind, content = el.get("type"), (el.get("content") or "").strip()
        if kind in SKIP_TYPES or not content:
            continue
        page = (el.get("bbox") or [{}])[0].get("page_id", 0) + 1
        if kind in ("title", "section_header"):
            section = content
            if content == title:  # already the chunk's first line
                continue
        text = table_to_text(content) if kind == "table" else content
        pieces.append((page, section, text))
    return _pack(title, pieces)


def chunk_text(title: str, text: str) -> list[Chunk]:
    """Chunks from Markdown or plain text: paragraphs, headings carried as the section."""
    pieces: list[tuple[int, str, str]] = []
    section = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        first = para.splitlines()[0]
        if first.startswith("#"):
            section = first.lstrip("#").strip()
        pieces.append((1, section, para))
    return _pack(title, pieces)
