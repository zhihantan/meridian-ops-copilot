# Meridian ops copilot (T17)

An Anthropic SDK tool loop (`copilot/loop.py`) on Agent Bricks' managed `DurableAgentServer`, deployed as a
Databricks App. Every invocation runs as the caller: the Apps ingress supplies the caller's token
(`[auth.user] required = true`), knowledge search covers only the caller's entitled tiers, and the model call
goes through Unity Gateway as the caller. Build with `scripts/build_copilot.sh`, which builds the browser UI and
copies `src/meridian` and the shared config next to this code; deploy from the folder it prints with `-p`.

Opening the app's URL in a browser shows the Meridian Ops console (BUILD), a React and Vite app in `frontend/`
that the server (FastAPI) serves at `/`. Everything in it runs as the signed-in visitor:
- **Overview:** acquirer status from the gold tables.
- **Ops Copilot:** this agent, with each tool call, the runbook's steps and the citations as they arrive.
- **Genie:** the Genie space "Meridian payments (gold)" (NATIVE), with its SQL, rows and a chart (`runtime/genie.py`).
- **Knowledge:** the knowledge chatbot, T16's retrieval and cited answer over the tiers the visitor can read
  (`runtime/knowledge.py`).
- **Approvals:** for meridian-admin, the refund batches waiting for approval, approved through
  `agent.approve_refund`, which alone decides (`runtime/ui.py`).
- **About:** the architecture of the whole POC, each box labelled NATIVE, PREVIEW, BUILD or EXTERNAL and linked to
  its asset in the workspace, with the demo's scenes as walkthroughs (`runtime/about.py`). The links to bundle
  resources come from `databricks bundle summary` at build time (`scripts/console_links.py`), without the host.

The first chat page stays at `/classic`. To work on the UI, run the server locally on port 8000 and
`npm run dev` in `frontend/`, which proxies `/api` to it.
