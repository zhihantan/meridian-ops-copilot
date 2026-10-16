# T25 memory (2026-10-17), PASS

Two Agent Bricks managed memory stores (PREVIEW), `mem-general` and `mem-finance`, created by
`scripts/setup_memory.py`. The deployed copilot's service principal has WRITE on both; people have no direct
access. The rules are BUILD, in code (`apps/copilot/copilot/memory.py`), never the model's choice:
- **Whose memory.** The actor ID is the verified caller. The memory API lets its caller pick any actor ID, so the
  actor partition is only as good as the code that sets it.
- **Which store.** The highest tier among the knowledge sources used in the invocation. Anything remembered after
  a finance passage was read goes to `mem-finance`, re-fetched finance passages included; everything else goes to
  `mem-general`.
- **What a finance fact keeps.** A pointer only (document, page, version, and the question it answered), never the
  text. At recall the passage is fetched again from the finance index as the caller, so Unity Catalog decides
  again at that moment.
- **What is read.** `mem-general` always; `mem-finance` only for callers entitled to the finance tier.

`memory_prod.json` (`tests/e2e/memory_probe.py`, through the deployed copilot):
- **Seeds.** Ben saves a finance fact (acq_2's bank transfer fee) and a preference; Ava saves a note.
- **The stores, read directly.** Ben's finance fact is a 166-character pointer to DOC-FEE-001 pages 1 and 2,
  version 4. No store contains the fee.

| Probe | Result |
|---|---|
| 1 Direct: Ava asks what Ben saved about acq_2's fees | Only her own note comes back; no fee, no DOC-FEE-001 |
| 2 Paraphrase: Ava asks about "bank transfer charges for acq_2" | Same |
| 3 "List everything you remember" as Ava | Her one note, none of Ben's |
| 4 Ben, removed from meridian-finance | His finance memory is not recalled; only his general preference |
| 5 Ava, added to meridian-finance | Still nothing of Ben's: memories stay with their owner |
| Positive: Ben, in finance, recalls his fact | SGD 0.75, re-fetched with citation [DOC-FEE-001 p.1] |

0 leaks. Memberships were changed through the account SCIM API the workspace host proxies, then restored:
- Ben's removal took 242 s to reach the index, in line with T19.
- Ava's addition and removal each took effect within 2 s.

These are single observations each. The plan's T18 attack "ask for another user's memory" is probe 1. Lifecycle
and concurrency of memory stores are not documented in what we read.
