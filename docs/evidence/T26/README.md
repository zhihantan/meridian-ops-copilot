# T26 long run and recovery (2026-10-17), PARTIAL

**Shown.** Long runs go in background mode: the invocation returns `queued`, and polling `/api/invocations/<id>`
returns `completed` with the output (T17). Every long evaluation since then has used it:
- the mixed questions (T22);
- the workflow and attack drills (T18), whose full RB-014 runs take 80 to 95 s;
- the leakage and memory probes (T19, T25).

**Not shown.** Recovering a run after a crash or redeploy. The copilot registers `app.recover(invoke)`, but the
runtime never resumes work under request-user authorization, and every copilot run is one: `[auth.user]
required = true`, so each tool runs as the caller. That is the design choice T17 to T25 rely on, and it is stated
as a known gap. Showing recovery would take a separate agent that runs as its own app identity: a checkpointed
5-minute task, stopped mid-run, then resumed by the recover handler. It is not built here.

The other half of a long run is the workflow, whose state survives without the runtime. A RB-014 run waiting for
approval is held in the database (`agent.runs`, `step_log`, `approvals`). A new invocation hours later continues
it from there (T18 happy path), whatever happened to the process in between.
