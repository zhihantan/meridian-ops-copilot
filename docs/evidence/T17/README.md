# T17 agent (2026-10-16)

`agent-bricks-meridian-copilot` (Databricks App): an Anthropic SDK tool loop (`apps/copilot/copilot/loop.py`) on Agent
Bricks' managed `DurableAgentServer`, built with `scripts/build_copilot.sh` and deployed with `agentbricks deploy`.

| Done when | Status | Evidence |
|---|---|---|
| Deployed agent answers a KB question with citations as Ava and as Ben | PASS | `copilot_probe.json`: each persona calls with its own OAuth token; both get a cited general answer (refund approval, DOC-REF-003 / DOC-RB-021) |
| Finance content only for the entitled | PASS | Ben gets the acq_7 SLA credit cited to DOC-FEE-001; Ava gets "I don't have that in the knowledge base", and her search never touched the finance index |
| Sync, stream and background modes | PASS | sync returns the output; stream emits `run.started`, a `message` per step, `run.completed`; background returns `queued`, then `completed` on polling |

How identity works (no model judgment involved):
- `[auth.user] required = true`: the Apps ingress forwards each caller's own downscoped token
  (scopes `vector-search`, `ai-gateway`, `model-serving`, `sql`); the tools and the model call run as the caller.
  Without a caller token the invocation fails; there is no fallback to the app's identity.
- `search_kb` resolves the caller's tiers from their groups (`config/scenario.yaml` `knowledge_tiers`), queries only
  those indexes with the caller's token (Unity Catalog grants apply too), drops any off-tier hit, and abstains below the
  reranker threshold before the model sees anything.
- The system prompt and tool definitions carry `cache_control`; traces go to the app's MLflow experiment, tagged with
  the caller and their tiers.

Not yet wired: `ask_genie` (T22), workflow tools `get_workflow`, `log_step`, `refund_batch` (T18), memory (T25).

**Chat page (2026-10-21), BUILD.** Opening the app's URL in a browser returned `{"detail":"Not Found"}`: the server
had only the invocation API. `/` now serves `apps/copilot/runtime/chat.html`, which calls that API from the browser
(background, with the event stream for each step) and shows the steps, the answer and its citations. The Apps ingress
signs the visitor in and forwards their token, so the copilot runs as them. Answers are escaped before formatting.
- **Same packages.** The redeploy set `exclude-newer` to the previous deploy's time (2026-10-16 19:42 UTC):
  databricks-agentbricks 0.6.0 came out an hour after it. The app reused its environment; only its own code was rebuilt.
- **Nothing else changed.** The deployed `app.yaml` is identical to the previous deploy's. The other code differences are
  job modules added since then, which the copilot does not import.
- **Checked:** `/` returns the page (200, HTML). A question sent the way the page sends it ran
  `run.started`, a tool call, its result, the answer and `run.completed` in 16 s, citing DOC-RB-014. The page itself
  was tested against a local stand-in: steps, follow-ups, errors, a new conversation, and escaped markup.

**Chat page, second version (2026-10-21), BUILD.** `runtime/ui.py` serves the page and its own small API. The page
shows:
- **Who is signed in,** from their own identity (`GET /api/me`), with the knowledge tiers their groups give them.
- **Each tool call as a step,** with its time and sources. A runbook run shows each step's state (done, waiting for
  approval, refused); the copilot's step events now carry the runbook's step names for this.
- **Answers** with tables, lists, citations coloured by source, a sources row and a copy button. The conversation
  survives a reload in the same tab.
- **For meridian-admin, the refunds waiting for approval** (`GET /api/approvals`, requesters shown by persona). Approve
  calls `agent.approve_refund` as the signed-in admin (`POST /api/approvals/{id}`), and the procedure decides; the page
  only hides the button on the admin's own request. The POST needs a custom header, so a cross-site form cannot send
  one.

Checked on the deployed app: the page loads, and `/api/me` gives the admin's tiers (general, finance). No approval is
pending. An approval without the header gets 400, and one for a made-up id gets the procedure's refusal ("no pending,
unexpired approval with that id") before anything is written. A suggested question answered in 15 s, citing
DOC-RB-021. `app.yaml` is unchanged. Against a local scripted copilot: the runbook view (s1 to s5, waiting at s5), the
approval cards, the confirmation and the refusal note, reload, and escaped markup.

**Console (2026-10-22), BUILD.** The browser UI is now a React and Vite app (`apps/copilot/frontend`), built by
`scripts/build_copilot.sh` into the app and served by its FastAPI server at `/`; the first page stays at `/classic`.
It has five pages, and every call runs as the signed-in visitor:
- **Overview:** acquirer status from `gold.acquirer_status`, degraded first, with links into the other pages.
- **Ops Copilot:** the agent, as before: each tool call, the runbook's steps and the citations as they arrive. A
  reload resumes a run that is still going, since the invocation continues on the server.
- **Genie** (`runtime/genie.py`): the Genie space "Meridian payments (gold)" asked directly. The page polls each
  message, then shows Genie's text, its SQL, the rows and a chart. Follow-ups continue the same Genie conversation.
- **Knowledge** (`runtime/knowledge.py`): T16's retrieval and grounded answer (`meridian.kb.retrieve`,
  `meridian.agent.answer`) as a chatbot. It streams the passages from the visitor's tiers first, then the cited
  answer; code abstains below the reranker threshold.
- **Approvals:** pending batches with Approve (the procedure decides), and the latest decided ones.

Checked on the deployed app, as the presenter, through the Apps ingress: the page and its assets load (gzip on assets
only, so the event streams are not buffered); `/api/me` gives general and finance; the overview shows acq_7
degraded; the decided list shows RB-832eed0860, approved and executed on 17 Oct. "How long does a refund approval
stay valid?" was answered from 5 passages, citing DOC-RB-021. Genie answered "Which acquirers are degraded right
now?" with one query in 18 s, and the copilot answered a runbook question in 8 s. `app.yaml` is unchanged. Locally,
against a scripted copilot: the runbook view, the approval cards and their confirmation, and markup that stays text.

**End to end as Eli, Ben and Ava** (`scripts/console_check.py`, `console_check_2026-10-21.json`, run 02:30 SGT on 22 Oct
against the deployed app, each with their own token): 15 of 15 checks PASS.
- **Identity:** Eli is an admin with the general and finance tiers; Ben has general and finance and is not an admin;
  Ava has general only.
- **Knowledge:** the finance SLA question is cited to DOC-FEE-001 for Eli and Ben. Ava's search covers only the
  general tier, returns no finance passage, and she gets "I don't have that in the knowledge base". A general
  question cites DOC-RB-021 for both Eli and Ava, and an out-of-scope question abstains.
- **Genie** answers as each persona, naming acq_7, and a follow-up continues the same conversation.
- **Approvals:** Eli sees the decided batch RB-832eed0860, approved and executed. Unity Catalog refuses Ava the
  approval tables ("Insufficient privileges"). An approval without the console's header gets 400, and a made-up
  approval gets the procedure's refusal.
- **Copilot** answers as Eli and as Ava; the overview shows acq_7 degraded among 7 acquirers.

The bundle is gzipped (135 KB of 444 KB sent), and the chart library loads only with Genie's first chart. The real UI
was also driven against the deployed backend through a local proxy holding the presenter's token: a copilot answer
resumed after a reload mid-run and finished in 30 s, Genie's hourly chart drew both series, the knowledge chatbot
abstained with its closest passages below the threshold, and Approvals listed the decided batches. The browser console
showed no errors.

**About page (2026-10-22), BUILD.** A sixth page draws the architecture of the whole POC
(`frontend/src/architecture.ts`). It opens with the problem the POC addresses and what it does, which the
presenter can hide for the tab. The diagram has 36 boxes in five lanes (sources, ingest, lakehouse, AI and agents,
experiences) and two bands (govern and observe; deliver and operate), each labelled NATIVE, PREVIEW, BUILD or EXTERNAL.
- **Click:** a box, or one of its table and job chips, opens that asset in the workspace in a new tab, where the
  workspace checks the visitor's own permissions.
- **Hover:** shows what the box does, what the click opens and its evidence, and draws its connections.
- **Scenes:** each scene of the run of show is a walkthrough through the boxes, with Play, numbered steps and the
  arrow keys.

No URL is stored in the repo. At build time, `scripts/console_links.py` keeps the paths, without the host, of the
bundle's jobs, pipelines and dashboard from `databricks bundle summary` (prod and staging). `GET /api/about`
(`runtime/about.py`) adds the workspace host, the Genie space (looked up as the visitor), the app, its trace
experiment and the model endpoints. Unity Catalog objects are linked by name.

Checked on 22 Oct, 10:08 SGT: `console_check.py` passed 16 of 16 against the deployed app
(`console_check_2026-10-22.json`). The new check finds links for the bundle's jobs, pipeline and dashboard, the
staging test, the prod deployment folder, the Genie space, the app and its traces, and no host in any stored path.
Locally, every box's link was compared with the workspace paths (74 links, all opening a new tab), with hover, the
walkthroughs, the label highlight and a 1280-pixel screen; the browser console showed no errors. Not checked: opening
each link in a signed-in browser.
