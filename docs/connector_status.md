# Knowledge source connectors (T11)

Checked against Databricks documentation on 2026-10-16. Built here: files in a Unity Catalog volume and Slack
history pages. Drive and Jira are documented, not built.

| Source | Mechanism | Status | Auth | Incremental | Deletes | Failure surface |
|---|---|---|---|---|---|---|
| Files (S3 in production; a managed UC volume in this POC) | `kb_sync` job reads the landing folder through `kb.v_source_docs` (`read_files`, binary); a file-arrival trigger on the folder starts it | GA building blocks (volumes, `read_files`, file-arrival triggers, `ai_parse_document`) | the job's identity with `READ VOLUME`; in production an external location on the S3 prefix | yes: content hash per document, only new or changed documents are parsed and rechunked | yes: a document gone from the folder has its chunks hard-deleted on the next run | `kb.ingest_failures` (document, stage, reason), job failure email |
| Slack messages | **BUILD**: a puller writes `conversations.history` pages to `kb/slack/history/<channel>/`, then `kb_sync` as above. In this POC the pages are a synthetic export (no live Slack workspace yet) | no managed Lakeflow Connect connector for message content found ([SaaS connectors](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/saas-overview)); the Slack Access and Integration Logs connector covers login and app activity, not messages | Slack bot token as a Unity Catalog secret (T08) | yes: cursor on the last `ts` (puller), content hash (`kb_sync`) | a message deleted in Slack is gone only if the puller re-reads the window; edits and deletes need the puller to refetch history or consume events | puller job failure; `kb.ingest_failures` for messages from a channel with no tier |
| Google Drive | Lakeflow Connect managed connector, `gdrive_options`, `BINARYFILE` ingestion into a table, then the same parse and chunk step | **GA** since 2026-08-04 ([release notes](https://docs.databricks.com/aws/en/release-notes/product/2026/august)) | Google connection in Unity Catalog | yes, per file: new and updated files ([FAQ](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/google-drive-faq)) | tracked only when ingesting a **shared drive**, not a folder ([limits](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/google-drive-limits)); files over 100 MB may fail | pipeline event log and update status |
| Jira | Lakeflow Connect managed connector | **Beta** ([Jira pipeline](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/jira-pipeline)) | Jira connection in Unity Catalog | yes (managed pipeline updates) | issues: not tracked by default; `use_audit_logs: true` needs a paid Jira plan and an admin connection user, and audit-log retention limits how far back deletes are found; comment and worklog deletes need a full refresh ([FAQ](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/jira-faq)) | pipeline event log and update status |

## Access tiers

A source's tier decides which chunk table and index its content reaches, in code, never by the model:
files take the tier of their folder (`kb/files/general/`, `kb/files/finance/`); Slack channels take the tier
listed in `config/scenario.yaml` (`knowledge_slack_channels`). A file in any other folder, or a channel that
is not listed, is not indexed and is recorded in `kb.ingest_failures` (fail closed).
