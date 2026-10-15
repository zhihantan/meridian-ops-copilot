# T04 Data Classification time-to-tag (measurement in progress)

- Classification enabled on `meridian_dev`, `meridian_staging`, `meridian`: 2026-10-15 16:40 SGT
- Prod `meridian.silver.customers` created: 2026-10-15 18:41 SGT, with no manual tags
- Check with: `SELECT column_name, tag_name FROM meridian.information_schema.column_tags WHERE schema_name = 'silver'`
- Expected tags: `class.email_address`, `class.phone_number`, `class.sg_nric`, `class.credit_card`,
  `class.date_of_birth`, `class.name`, `class.street_address`, and later `secondary_email -> class.email_address`

| Checked at | Columns tagged | Notes |
|---|---|---|
| 2026-10-15 18:45 SGT | 0 of 8 | scan not yet run on the new table |
