# T08 secrets (2026-10-15)

Unity Catalog secrets are GA (since 2026-08-03), not preview; labels corrected.

| Done when | Status | Evidence |
|---|---|---|
| Rotation works without redeploy | PASS | `rotation_dev.json`: the deployed `meridian-secret-probe` job read fingerprint `4b3f2d80dd6d`, the value was rotated, the next run read `144911b30fe3`; nothing deployed in between |
| Grant to a group, not a person | PASS | `config/access_matrix.csv`: `meridian-de` gets `USE SCHEMA` on `<catalog>.secrets` and `READ SECRET` on each secret, dev only. Staging and prod jobs run as the CI principal, which deploys and owns the catalog's objects; no persona group reads prod secrets |
| A restricted user cannot read the secret | PASS | `access_dev.json`: Gus (data engineer) allowed, same fingerprint; Ava (support) denied with `PermissionDenied` |
| Audit row | PASS | `access_dev.json` `audit`: `getSecret` 200 for Gus's principal and the owner, `getSecret` with an error status for Ava's denied reads, `updateSecret` for the rotation, `createSecret`; `service_name = 'unityCatalog'`, `request_params.full_name` names the secret |
| Per-environment names through bundle variables | PASS | jobs take `${var.catalog}.secrets.<name>`: `meridian_dev`, `meridian_staging`, `meridian` |

How jobs read secrets: `dbutils.secrets.get(catalog=, schema=, key=)` (serverless environment 4+), REST as a
fallback; values are never printed, only a short sha256 fingerprint in drills.

Not built: an external secret manager (AWS Secrets Manager backing a schema is supported by Databricks, but this
POC has no AWS account of its own); HashiCorp Vault (no native backend found; answer sheet).

Findings: `READ SECRET` is not grantable on a schema on this metastore (privilege model 1.0), and `GRANT ... ON SECRET`
through the SQL warehouse fails with `UC_SECRETS_NOT_ENABLED`; the permissions REST API works.
