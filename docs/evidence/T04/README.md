# T04 PII governance with ABAC (2026-10-15, prod 2026-10-17), PASS

Native Unity Catalog ABAC policies on each catalog (`scripts/apply_governance.py`). The mask and filter functions in
the gov schema are BUILD.
- **Contact details.** Emails and phones are masked for everyone except admins and the pipeline principal.
- **Identifiers and dates of birth.** NRIC, card numbers and dates of birth are hidden.
- **Market row filter.** Support (Ava) sees home-market rows only; finance and admins see every market.

The policies match Data Classification's system tags (`class.*`), so they never name a column. A column is protected
as soon as it carries the tag, whether the classification scan set it or a manual fallback did.

| Evidence | What | Result |
|---|---|---|
| `persona_probe_dev.json` | The same queries as Ava, Ben and Eli on dev (tags set by hand) | PASS |
| `persona_probe_prod_untagged.json` | The same on prod before any tag: the policies have nothing to match | FAIL as expected: Ava saw the raw email and NRIC; the row filter applied |
| `persona_probe_prod.json` | The same on prod after the fallback tags | PASS, about 3 minutes after tagging |
| `genie_probe_dev.json` | The same policies in Genie: a temporary space over the protected silver tables; the same two questions as Ava, Ben and Eli; Genie's SQL recorded; the space deleted afterwards (`tests/e2e/genie_governance_probe.py`) | PASS, 7 of 7: Ava SG only, masked email, no NRIC; Ben every market, masked; Eli raw |
| `time_to_tag.md` | How long the classification scan takes to tag a new table | Nothing tagged in any catalog after about 39 hours; still measuring on staging |

Unmasked values never reach the evidence: the probes record them as `<unmasked, N chars>`.

The demo's Genie space (T22) holds only gold aggregates, which have no customer columns and no market column, so
the policies have nothing to act on there. Genie runs its SQL as the asker, so a protected table in a space is
masked and filtered per asker, as the Genie probe shows.

**Deviation.** The scan had not tagged prod after about 39 hours. Prod's tags were therefore set from the contracts'
`pii` fields with `apply_governance.py --target prod --manual-tags`. Until a column is tagged, the PII coverage check
(T05) flags it.
