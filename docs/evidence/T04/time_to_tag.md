# T04 Data Classification time-to-tag (prod tagged manually; still measuring on staging)

- Classification enabled on `meridian_dev`, `meridian_staging`, `meridian`: 2026-10-15 16:40 SGT
- Prod `meridian.silver.customers` created: 2026-10-15 18:41 SGT, with no manual tags
- Staging `meridian_staging.silver.customers` created: 2026-10-15 23:09 SGT, never tagged by hand
- Check with: `SELECT column_name, tag_name FROM <catalog>.information_schema.column_tags WHERE schema_name = 'silver'`
- Expected tags: `class.email_address`, `class.phone_number`, `class.sg_nric`, `class.credit_card`,
  `class.date_of_birth`, `class.name`, `class.street_address`, and later `secondary_email -> class.email_address`

| Checked at | Columns tagged | Notes |
|---|---|---|
| 2026-10-15 18:45 SGT | 0 of 8 | scan not yet run on the new table |
| 2026-10-17 05:10 SGT | 0 of 8 | still untagged after about 34.5 hours; the masks do not apply in prod until tagged (dev is tagged manually); fallback: `apply_governance.py --target prod --manual-tags` |
| 2026-10-17 09:30 SGT | 0 of 8 | still untagged after about 39 hours. Staging, which is never tagged by hand, has no `class.*` tags either, so the scan has tagged nothing in any catalog since it was enabled. Its results table (`system.data_classification.results`) needs a grant we do not have |
| 2026-10-17 14:19 SGT | 0 of 8 | Prod probe before tagging: FAIL. Ava saw the raw email and NRIC; only the market row filter applied (`persona_probe_prod_untagged.json`) |
| 2026-10-17 14:19 SGT | prod: 7 manual | Fallback applied in prod: `apply_governance.py --target prod --manual-tags` set 7 tags from the contracts. Prod probe at 14:22: PASS (`persona_probe_prod.json`). The policies did not change; only the tags they match arrived |

From here the measurement continues on staging only (prod's tags are now manual).
