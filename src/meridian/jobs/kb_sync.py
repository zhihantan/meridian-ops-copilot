"""Knowledge sync (T12, BUILD): sources to kb.docs to per-tier chunk tables, incrementally.

Reads kb.v_source_docs, hashes every document and compares with kb.docs: new and changed documents are
parsed (ai_parse_document for PDF and DOCX, as-is for Markdown, text and Slack), chunked and written to
kb.chunks_<tier>, replacing that document's old chunks; unchanged documents are not touched; documents
gone from the source have their chunks hard-deleted. The chunk tables have Change Data Feed on, so the
Delta Sync indexes follow. A document that fails is written to kb.ingest_failures and keeps its previous
chunks; it is retried on the next run. --full-refresh reprocesses every document.

    kb_sync.py --catalog C --bronze-schema S --kb-root /Volumes/.../raw/kb --sql-file .../sql/kb_objects.sql
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

import json
from datetime import UTC, datetime

import yaml
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from meridian.common.sqlfile import statements
from meridian.jobs.common import names, parser
from meridian.kb.chunking import chunk_id, chunk_parsed, chunk_text

TIERS = ("general", "finance")
PARSED_FORMATS = ("pdf", "docx")
TEXT_FORMATS = ("md", "txt", "slack")
CHUNK_SCHEMA = ("chunk_id STRING, doc_id STRING, title STRING, source STRING, uri STRING, tier STRING, page INT, "
                "seq INT, text STRING, doc_revision INT, source_version STRING, modified_at TIMESTAMP, "
                "synced_at TIMESTAMP, run_id STRING")


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--kb-root", required=True)
    p.add_argument("--sql-file", required=True)
    p.add_argument("--scenario", help="config/scenario.yaml (Slack channel tiers)")
    p.add_argument("--full-refresh", default="false")
    args = p.parse_args()
    full_refresh = args.full_refresh.lower() == "true"
    n = names(args)
    spark = SparkSession.builder.getOrCreate()
    kb = f"{n.catalog}.{n.schema('kb')}"
    started = datetime.now(UTC)

    for statement in statements(args.sql_file, {"kb": kb, "kb_root": args.kb_root}):
        spark.sql(statement)
    scenario = yaml.safe_load(Path(args.scenario).read_text()) if args.scenario else {}
    channels = scenario.get("knowledge_slack_channels", {})
    spark.createDataFrame(list(channels.items()), "channel STRING, tier STRING").write.mode("overwrite") \
        .saveAsTable(f"{kb}.channel_tiers")

    source = spark.sql(f"""
        SELECT doc_id, source, uri, format, tier, title, source_version, modified_at,
               sha2(coalesce(content_bytes, encode(content_text, 'UTF-8')), 256) AS content_hash
        FROM {kb}.v_source_docs""").collect()
    rows = {r["doc_id"]: r for r in spark.table(f"{kb}.docs").collect()}
    known = {doc_id: r for doc_id, r in rows.items() if r["deleted_at"] is None}  # live documents

    failures: list[tuple] = []
    todo, unchanged = [], 0
    for doc in source:
        if doc["tier"] not in TIERS:  # fail closed: no tier, no index
            failures.append((doc["doc_id"], doc["uri"], "tier", f"no access tier for {doc['uri']}"))
            continue
        old = known.get(doc["doc_id"])
        if full_refresh or old is None or old["content_hash"] != doc["content_hash"] or old["tier"] != doc["tier"]:
            todo.append(doc)
        else:
            unchanged += 1
    seen = {d["doc_id"] for d in source if d["tier"] in TIERS}  # a document that lost its tier is removed
    gone = [doc_id for doc_id in known if doc_id not in seen]

    # Parse the binary documents in one call; ai_parse_document reports per-document errors in its output.
    parsed: dict[str, dict] = {}
    binary = [d["doc_id"] for d in todo if d["format"] in PARSED_FORMATS]
    if binary:
        listed = ", ".join(f"'{d}'" for d in binary)
        for r in spark.sql(f"""SELECT doc_id, CAST(ai_parse_document(content_bytes) AS STRING) AS parsed
                               FROM {kb}.v_source_docs WHERE doc_id IN ({listed})""").collect():
            parsed[r["doc_id"]] = json.loads(r["parsed"]) if r["parsed"] else {}
    texts = {r["doc_id"]: r["text"] for r in spark.sql(f"""
        SELECT doc_id, coalesce(content_text, decode(content_bytes, 'UTF-8')) AS text FROM {kb}.v_source_docs
        WHERE format IN ({", ".join(f"'{f}'" for f in TEXT_FORMATS)})""").collect()}

    now = datetime.now(UTC)
    chunk_rows, doc_rows = [], []
    for doc in todo:
        try:
            if doc["format"] in PARSED_FORMATS:
                result = parsed.get(doc["doc_id"]) or {}
                if result.get("error_status") or not result.get("document", {}).get("elements"):
                    raise ValueError(f"ai_parse_document: {result.get('error_status') or 'no content extracted'}")
                chunks = chunk_parsed(doc["title"], result)
            elif doc["format"] in TEXT_FORMATS:
                chunks = chunk_text(doc["title"], texts.get(doc["doc_id"]) or "")
            else:
                raise ValueError(f"unsupported format {doc['format']}")
            if not chunks:
                raise ValueError("document has no text")
        except Exception as exc:  # noqa: BLE001  one bad document never stops the run
            failures.append((doc["doc_id"], doc["uri"], "parse", f"{type(exc).__name__}: {str(exc)[:300]}"))
            continue
        old = rows.get(doc["doc_id"])  # a re-added document continues its revision count
        revision = (old["revision"] if old else 0) + (0 if old and old["content_hash"] == doc["content_hash"] else 1)
        for c in chunks:
            chunk_rows.append((chunk_id(doc["doc_id"], doc["content_hash"], c.seq), doc["doc_id"], doc["title"],
                               doc["source"], doc["uri"], doc["tier"], c.page, c.seq, c.text, revision,
                               doc["source_version"], doc["modified_at"], now, args.run_id))
        doc_rows.append((doc["doc_id"], doc["source"], doc["uri"], doc["format"], doc["tier"], doc["title"],
                         doc["source_version"], revision, doc["content_hash"], len(chunks), doc["modified_at"],
                         now, now, None, args.run_id))

    # Replace the chunks of every rewritten or deleted document, in both tier tables (a tier can change).
    replaced = [d[0] for d in doc_rows] + gone
    deleted_chunks = 0
    if replaced:
        listed = ", ".join(f"'{d}'" for d in replaced)
        for tier in TIERS:
            deleted_chunks += spark.sql(f"DELETE FROM {kb}.chunks_{tier} WHERE doc_id IN ({listed})") \
                .first()["num_affected_rows"]
    chunks_df = spark.createDataFrame(chunk_rows, CHUNK_SCHEMA)
    for tier in sorted({row[5] for row in chunk_rows}):  # no empty commits for the index to sync
        chunks_df.where(F.col("tier") == tier).write.mode("append").saveAsTable(f"{kb}.chunks_{tier}")

    if doc_rows:
        spark.createDataFrame(doc_rows, spark.table(f"{kb}.docs").schema).createOrReplaceTempView("synced")
        spark.sql(f"""MERGE INTO {kb}.docs t USING synced s ON t.doc_id = s.doc_id
                      WHEN MATCHED THEN UPDATE SET t.source = s.source, t.uri = s.uri, t.format = s.format,
                        t.tier = s.tier, t.title = s.title, t.source_version = s.source_version,
                        t.revision = s.revision, t.content_hash = s.content_hash, t.chunks = s.chunks,
                        t.modified_at = s.modified_at, t.last_changed_at = s.last_changed_at,
                        t.deleted_at = NULL, t.run_id = s.run_id
                      WHEN NOT MATCHED THEN INSERT *""")
    if gone:
        listed = ", ".join(f"'{d}'" for d in gone)
        spark.sql(f"UPDATE {kb}.docs SET deleted_at = current_timestamp(), chunks = 0, run_id = '{args.run_id}' "
                  f"WHERE doc_id IN ({listed})")
    if failures:
        spark.createDataFrame([(now, args.run_id, *f) for f in failures],
                              "failed_at TIMESTAMP, run_id STRING, doc_id STRING, uri STRING, stage STRING, reason STRING") \
            .write.mode("append").saveAsTable(f"{kb}.ingest_failures")

    new = sum(1 for d in doc_rows if d[0] not in known)  # includes re-added documents
    run = (started, datetime.now(UTC), args.run_id, full_refresh, len(source), new, len(doc_rows) - new, unchanged,
           len(gone), len(failures), len(chunk_rows), deleted_chunks)
    spark.createDataFrame([run], spark.table(f"{kb}.sync_runs").schema).write.mode("append") \
        .saveAsTable(f"{kb}.sync_runs")
    print(f"kb_sync {args.run_id}: {len(source)} source docs; new {new}, changed {len(doc_rows) - new}, "
          f"unchanged {unchanged}, deleted {len(gone)}, failed {len(failures)}; "
          f"chunks written {len(chunk_rows)}, deleted {deleted_chunks}")
    for f in failures:
        print(f"  failed {f[0]} at {f[2]}: {f[3]}")


if __name__ == "__main__":
    main()
