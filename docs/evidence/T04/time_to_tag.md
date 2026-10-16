# T04 Data Classification time-to-tag (measurement in progress)

- Classification enabled on `meridian_dev`, `meridian_staging`, `meridian`: 2026-10-15 16:40 SGT
- Prod `meridian.silver.customers` created: 2026-10-15 18:41 SGT, with no manual tags
- Check with: `SELECT column_name, tag_name FROM meridian.information_schema.column_tags WHERE schema_name = 'silver'`
- Expected tags: `class.email_address`, `class.phone_number`, `class.sg_nric`, `class.credit_card`,
  `class.date_of_birth`, `class.name`, `class.street_address`, and later `secondary_email -> class.email_address`

| Checked at | Columns tagged | Notes |
|---|---|---|
| 2026-10-15 18:45 SGT | 0 of 8 | scan not yet run on the new table |
| 2026-10-17 05:10 SGT | 0 of 8 | still untagged after about 34.5 hours; the masks do not apply in prod until tagged (dev is tagged manually); fallback: `apply_governance.py --target prod --manual-tags` |
