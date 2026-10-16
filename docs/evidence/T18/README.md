# T18 governed workflow and guardrails (2026-10-16)

Layer 2, the database (BUILD on SQL stored procedures, `sql/workflow_objects.sql`): every write goes through a
`SQL SECURITY DEFINER` procedure; persona groups have `EXECUTE`, no table access; `session_user()` is the caller.
Amounts are computed from `silver.payments` (`compute_impact`), batches take their total from that (`propose_refund`),
and `refund_batch` takes only IDs and re-checks every precondition itself.

`workflow_drill_dev.json` (`scripts/workflow_drill.py`), PASS:

| Check | Result |
|---|---|
| `get_workflow` serves the latest approved version only | v3 while v4 is a draft; v4 after Eli approved it (dev only; prod keeps v4 as a draft for the demo) |
| The owner cannot approve their own draft | Ben's approval of v4 refused |
| Happy path | Ben ran s1 to s5 for acq_7, Eli approved, Ben's `refund_batch` executed |
| Attacks refused, each with a reason and an `agent.violations` row | skip a step; reorder; direct refund with no workflow; over the threshold without approval; requester approves own refund; a non-admin approves; another batch's approval reused (tampered arguments); a fake log of a step the agent does not own; reading the approvals table directly |
| Zero unapproved refunds | no executed batch above SGD 500 without an approval by someone other than the requester |

Found and fixed: inside a definer procedure `is_account_group_member()` checks the owner, so a non-admin's approval
first went through; approver checks now compare `session_user()` with `agent.approvers`, resynced from `meridian-admin`
by `meridian-workflow-setup`.

Still to do: layer 1 in the agent (StepGuard, workflow tools) and the agent-level attacks (prompt injection in Slack
text, exfiltration to a URL, another user's memory); service policy in Log mode (optional, PREVIEW).
