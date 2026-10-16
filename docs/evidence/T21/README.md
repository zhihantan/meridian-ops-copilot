# T21 audit (2026-10-17), PASS

**What is recorded.** `kb.audit_log` (ts, actor, action, target, reason, details) is written by every governed
procedure: workflow and refund approvals, refunds, and correction proposals, decisions and refusals. kb_sync
writes it too, for each document it adds, changes or deletes. A reverted correction's deletion reads
"correction reverted".

**Per-document provenance.** `obs.v_kb_changes` (in the obs schema; there is no separate audit schema) gives
each knowledge document:
- its version and last sync, from `kb.docs`;
- who last changed the source, when and why:
  - files: the latest `filesPut` or `filesDelete` on its path, in `system.access.audit`;
  - corrections: the approver and the reason;
  - Slack: the author;
- the latest `kb.audit_log` entry.

`system.access.audit` is not real-time, so a very recent file write can be missing from the view for a while.

**The export.** `meridian-export-audit` runs daily at 00:45 SGT. It refreshes the views and writes dated CSV files to
`/Volumes/<catalog>/obs/exports/audit/<date>/`:
- `kb_changes`, `audit_log`, `corrections` and `violations`;
- the Delta table history of `kb.docs` and `kb.corrections` (DESCRIBE HISTORY, which a view cannot hold);
- a manifest.

`trace_dev.json` (`scripts/audit_trace.py --target dev`) asks three questions, answered from files, from Slack, and
from an approved correction. It looks up every cited document:

| Answer cites | Version | Last editor | When | Reason |
|---|---|---|---|---|
| DOC-RB-021, DOC-REF-003, DOC-RB-014, DOC-NOTE-250 (files) | manifest version and sync revision | the identity that wrote the file (`filesPut`) | file write time | `filesPut`, plus the sync that indexed it |
| SLACK-OPS-004 | sync revision | the message author | message time | Slack message |
| CORR-5EAB54A9 (correction) | correction version 1 | the approver (Eli); submitted by Ava | approval time | "approved: drill: checked with the owning team" |

Today's export folder exists with all seven files (`export_files` in the JSON). Principals appear by persona
name in evidence files (`meridian.common.personas`).
