# T10 knowledge corpus (2026-10-16)

| Done when | Status | Evidence |
|---|---|---|
| 8 documents: 3 PDF, 2 DOCX, 3 Markdown or text, plus a 25-message Slack export | PASS | `src/meridian/synth/corpus.py` (seeded; facts from `config/scenario.yaml` and the RB-014 workflow), `tests/test_corpus.py` |
| Files in the landing location; manifest lists doc_id, tier, expected facts | PASS | `scripts/land.sh <target> kb` puts each file under `kb/files/<tier>/` of the landing volume (dev and prod), with `manifest.csv` beside them. Tiers: the fee schedule with the acq_7 SLA is `finance`; the rest `general` |

A managed Unity Catalog volume stands in for the S3 `knowledge/` prefix (no AWS account of our own in this POC).
