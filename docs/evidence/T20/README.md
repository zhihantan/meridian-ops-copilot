# T20 feedback and corrections (2026-10-17), PASS

**Feedback and corrections** (BUILD) are SQL SECURITY DEFINER procedures in `sql/kb_feedback.sql`: `submit_feedback`,
`submit_correction`, `approve_correction`, `reject_correction`, `revert_correction` and `list_corrections`. Persona
groups have EXECUTE on the kb schema and no access to the tables.
- **Proposing.** Anyone may propose a correction to a tier they are entitled to.
- **Deciding.** A member of meridian-admin approves or rejects it, never the person who submitted it, and can
  revert an approved one. Every decision and refusal is written to `kb.audit_log`.
- **Serving.** An approved correction becomes a knowledge document (`source = 'correction'`, cited like
  `[CORR-5EAB54A9 p.1]`), because `kb.v_source_docs` includes approved corrections. kb_sync then indexes it like
  any other source, and a revert removes it on the next sync.

`corrections_dev.json` (`scripts/corrections_drill.py --target dev`):
- **The questions.** Four knowledge gaps from `config/feedback_questions.yaml`, separate from the golden set. Each
  is asked as the persona whose tier it needs, through the copilot's retriever and answer step.
- **Feedback and corrections.** Each asker gives feedback (down) and proposes the correction.
- **Decisions.** Eli approves two, rejects one and leaves one proposed.

| Check | Result |
|---|---|
| Every gap fails at baseline | 4 of 4 abstained |
| At least 2 improved after approval | 2 of 2: F01 and F02 now state the key fact and cite their correction |
| Rejected and unreviewed corrections are not served | F03 (rejected) and F04 (proposed) still abstain |
| No regression on the test split | Golden test split, T16's code checks: 8 of 10 before, 8 of 10 after, the same two misses |
| Revert stops it being served | F02 reverted: gone from the index 48 s after the next kb_sync; asked again, the answer no longer cites it |
| Attacks refused, each with a reason | Ava proposes a finance correction; Ava approves; Eli approves his own; a rejected correction is approved; Ava reads `kb.corrections` |

Timing:
- **Approval to served:** kb_sync runs in about 3 to 4 minutes, and the index shows the correction about 13 s after
  that. The 10-minute sweep (T14) does this unattended.
- **Re-runs:** the drill first reverts approved corrections left over from an earlier run, the governed way, so it
  can be repeated.

Found and fixed:
- **Version type.** The source view's `source_version` took BIGINT from the manifest CSV, so the first correction
  (`'v1'`) failed the cast. Versions are now strings everywhere.
- **Lowercase IDs.** Correction IDs were lowercase hex, which the citation pattern (uppercase IDs like `DOC-` and
  `SLACK-`) did not match. They are uppercase now.
