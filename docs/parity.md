# Local development parity (T07)

Tested by `scripts/parity_check.py` over Databricks Connect on serverless on 2026-10-15. connect: runs from local code, execution remote. remote only: needs a workspace notebook, job or pipeline. not supported: no equivalent through Connect.

| Capability | Result | Note |
|---|---|---|
| PySpark DataFrame API | connect |  |
| Spark SQL | connect |  |
| dbutils subset (fs, secrets) | connect | WorkspaceClient().dbutils provides fs and secrets; notebook, widgets and library utilities are notebook-only |
| Python UDFs | connect | local Python minor version must match the serverless environment (3.12) |
| MLflow | connect | tracking API to the workspace through databricks-sdk; the mlflow client pinned by serverless 4 (mlflow-skinny 2.22) did not resolve from this laptop's package mirror |
| AI Functions | connect | SQL functions run on serverless; billed per token |
| Volume reads and writes | connect | through Spark or the Files API; local open() on /Volumes paths works only on Databricks compute |
| Auto Loader (cloudFiles) | connect | streaming with availableNow runs on serverless |
| display() | not supported | VS Code notebooks with the Databricks extension render a local preview; scripts use df.show() |
| dbutils.widgets | not supported | the SDK's local dbutils.widgets is a stub with no values (get raises KeyError); local code takes arguments instead |
| %pip and magics | not supported | dependencies go through uv add locally and the bundle's serverless environment remotely |
| SDP pipeline code | remote only | pipeline decorators run in the pipeline engine: validate or run with a bundle deploy to dev |
