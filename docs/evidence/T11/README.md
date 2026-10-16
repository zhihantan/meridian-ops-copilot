# T11 sources and connector status (2026-10-16)

| Done when | Status | Evidence |
|---|---|---|
| Files flow into the source view | PASS | `kb.v_source_docs` (`sql/kb_objects.sql`): 8 files with tier from the folder, title, version and date from the manifest |
| Slack flows into the view | PASS (synthetic) | 25 messages from `conversations.history` pages under `kb/slack/history/<channel>/`, user names from `users.json`, tier from `knowledge_slack_channels`. The pages are a synthetic export: the live Slack puller waits for the Slack workspace (paused) |
| Drive and Jira documented, not built | PASS | `docs/connector_status.md`: mechanism, status, auth, incremental, deletes and failure surface per source, checked 2026-10-16 with links (Google Drive GA since 2026-08-04; Jira Beta; no managed Slack message connector found) |

Fail closed: a file outside `kb/files/general/` and `kb/files/finance/`, or a message from an unlisted channel, is
not indexed and lands in `kb.ingest_failures`.
