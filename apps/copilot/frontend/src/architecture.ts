// The architecture on the About page: every part of the POC, how the parts connect, and the demo's scenes as paths
// through them. A box's `ref` names what it opens in the workspace; About.tsx resolves refs to URLs with the
// paths /api/about returns, so nothing here names a workspace. Labels follow the POC's rule: NATIVE is a Databricks
// feature, PREVIEW one that is not yet generally available, BUILD code written for this POC, EXTERNAL not Databricks.
import {
  Activity,
  Bot,
  Brain,
  CalendarClock,
  ChartColumn,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  FolderGit2,
  FolderInput,
  GitBranch,
  History,
  Layers,
  LayoutDashboard,
  LineChart,
  Lock,
  MessageSquare,
  Package,
  Plug,
  Rocket,
  RotateCcw,
  ScanSearch,
  ScrollText,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  Table2,
  Telescope,
  Terminal,
  Waypoints,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export type Kind = "native" | "preview" | "build" | "external";
export type LaneId = "sources" | "ingest" | "lakehouse" | "ai" | "experience" | "govern" | "deliver";
export type EdgeKind = "data" | "trigger" | "ai" | "control" | "deliver" | "governs";

/** A link inside a box: `ref` uses the same notation as ArchNode.ref. */
export interface Asset {
  label: string;
  ref: string;
}

export interface ArchNode {
  id: string;
  lane: LaneId;
  column?: 0 | 1; // the AI lane has two: platform services, then the copilot
  push?: boolean; // start a group at the bottom of its lane, next to what it feeds
  title: string;
  sub: string;
  kinds: Kind[];
  icon: LucideIcon;
  /**
   * What the box opens. job:<bundle key> (prod) or job:staging/<key>, pipeline:, dashboard:, folder:prod, and
   * genie, app, experiment, search, endpoint:answer|embedding, all from /api/about; catalog, schema:<schema>,
   * table:<schema>.<name> (views and indexes too), volume:<schema>.<name>, fn:<schema>.<name> in the app's catalog;
   * github[:<path>] in the repository; page:<page> in this console.
   */
  ref?: string;
  assets?: Asset[];
  about: string;
  evidence?: string;
}

export interface ArchEdge {
  from: string;
  to: string;
  kind: EdgeKind;
  label?: string;
  quiet?: boolean; // drawn only when one of its boxes is in focus, to keep the full picture readable
}

export interface FlowStep {
  node: string;
  title: string;
  text: string;
}

export interface Flow {
  id: string;
  scene: string;
  title: string;
  steps: FlowStep[];
}

export const KINDS: { kind: Kind; label: string; text: string }[] = [
  { kind: "native", label: "Native", text: "A Databricks feature" },
  { kind: "preview", label: "Preview", text: "A Databricks feature not yet generally available" },
  { kind: "build", label: "Build", text: "Code written for this POC" },
  { kind: "external", label: "External", text: "Not Databricks" },
];

export const EDGE_KINDS: { kind: EdgeKind; label: string }[] = [
  { kind: "data", label: "Data" },
  { kind: "trigger", label: "Trigger" },
  { kind: "ai", label: "AI and tool calls" },
  { kind: "control", label: "Runbook and recovery" },
  { kind: "governs", label: "Policy" },
  { kind: "deliver", label: "Delivery" },
];

export const LANES: { id: LaneId; title: string; hint: string }[] = [
  { id: "sources", title: "Sources", hint: "Into a volume" },
  { id: "ingest", title: "Ingest", hint: "Lakeflow, and quality" },
  { id: "lakehouse", title: "Lakehouse", hint: "Unity Catalog" },
  { id: "ai", title: "AI and agents", hint: "Platform services, then the copilot" },
  { id: "experience", title: "Experiences", hint: "Who uses it" },
  { id: "govern", title: "Govern and observe", hint: "Unity Catalog, across every lane" },
  { id: "deliver", title: "Deliver and operate", hint: "From a branch to prod, and back" },
];

export const NODES: ArchNode[] = [
  // Sources
  {
    id: "files",
    lane: "sources",
    title: "Payment files",
    sub: "Volume, payments/",
    kinds: ["native"],
    icon: FolderInput,
    ref: "volume:landing.raw",
    about: "Synthetic payment and customer files land in a Unity Catalog volume. A new file in payments/ starts meridian-ingest through a file-arrival trigger.",
    evidence: "T02, T06",
  },
  {
    id: "kbfiles",
    lane: "sources",
    push: true,
    title: "Knowledge files",
    sub: "Policies, runbooks",
    kinds: ["native"],
    icon: FileText,
    ref: "volume:landing.raw",
    about: "Documents for the knowledge base land in the same volume, under kb/, by tier: general for everyone, finance for finance and admins. A new file starts meridian-kb-sync.",
    evidence: "T10",
  },
  {
    id: "slack",
    lane: "sources",
    title: "Slack history",
    sub: "#ops-incidents",
    kinds: ["build"],
    icon: MessageSquare,
    ref: "table:kb.channel_tiers",
    about: "There is no managed Slack message connector, so the knowledge base reads a Slack history export in the shape a puller writes. Only channels mapped to a tier are indexed.",
    evidence: "T10, T11",
  },

  // Ingest and quality
  {
    id: "ingest",
    lane: "ingest",
    title: "meridian-ingest",
    sub: "Job, file-arrival trigger",
    kinds: ["native"],
    icon: Workflow,
    ref: "job:ingest_job",
    assets: [
      { label: "ingest-sources", ref: "job:ingest_sources" },
    ],
    about: "One run holds the pipeline update, the quality checks, the escalation and the AI digest. Five more source feeds come in through a job generated from config/sources.yaml.",
    evidence: "T03, T06",
  },
  {
    id: "pipeline",
    lane: "ingest",
    title: "meridian-dlc",
    sub: "Declarative pipeline",
    kinds: ["native"],
    icon: Waypoints,
    ref: "pipeline:dlc",
    assets: [{ label: "event log", ref: "table:obs.pipeline_event_log" }],
    about: "A Lakeflow declarative pipeline: Auto Loader into bronze, then silver and gold. Its expectations are compiled from contracts/*.yaml (BUILD), and a critical rule fails the update.",
    evidence: "T03",
  },
  {
    id: "checks",
    lane: "ingest",
    title: "Quality checks",
    sub: "Drift, freshness, PII",
    kinds: ["build"],
    icon: Activity,
    ref: "job:ingest_job",
    assets: [
      { label: "drift_events", ref: "table:obs.drift_events" },
      { label: "freshness_events", ref: "table:obs.freshness_events" },
      { label: "pii_coverage", ref: "table:gov.pii_coverage" },
    ],
    about: "Tasks of meridian-ingest that run after the pipeline. A breach fails its task and sends an email; the escalate task posts the run's issues to Slack, which is paused in this POC, so they go to the job log.",
    evidence: "T05",
  },
  {
    id: "digest",
    lane: "ingest",
    title: "AI digest",
    sub: "ai_query on quarantine",
    kinds: ["build"],
    icon: Sparkles,
    ref: "table:obs.dq_digest",
    about: "Groups the quarantine by rule, and a pinned model writes a summary, likely cause and fix through ai_query. Counts come from SQL; every row is flagged AI-generated and not reviewed.",
    evidence: "T05b",
  },
  {
    id: "kbsync",
    lane: "ingest",
    push: true,
    title: "Knowledge sync",
    sub: "Incremental sync",
    kinds: ["build"],
    icon: RotateCcw,
    ref: "job:kb_sync_job",
    assets: [
      { label: "kb-sweep", ref: "job:kb_sweep_job" },
    ],
    about: "meridian-kb-sync reconciles the sources, updates only the documents that changed, then syncs the indexes. File-arrival triggers miss edits and deletes, so a sweep runs every 10 minutes.",
    evidence: "T12, T14",
  },

  // Lakehouse
  {
    id: "bronze",
    lane: "lakehouse",
    title: "Bronze",
    sub: "Raw records",
    kinds: ["native"],
    icon: Layers,
    ref: "schema:bronze",
    assets: [
      { label: "payments", ref: "table:bronze.payments" },
      { label: "customers_changes", ref: "table:bronze.customers_changes" },
    ],
    about: "Records as they arrived, with rescued data and ingestion metadata, as streaming tables of the pipeline.",
    evidence: "T03",
  },
  {
    id: "silver",
    lane: "lakehouse",
    title: "Silver",
    sub: "Validated and masked",
    kinds: ["native"],
    icon: Layers,
    ref: "schema:silver",
    assets: [
      { label: "payments", ref: "table:silver.payments" },
      { label: "customers", ref: "table:silver.customers" },
    ],
    about: "Validated, deduplicated records with PII handled. Column masks and the market row filter apply to every reader, through the ABAC policies.",
    evidence: "T03, T04",
  },
  {
    id: "gold",
    lane: "lakehouse",
    title: "Gold",
    sub: "Serving tables",
    kinds: ["native"],
    icon: Table2,
    ref: "schema:gold",
    assets: [
      { label: "acquirer_status", ref: "table:gold.acquirer_status" },
      { label: "acquirer_hourly", ref: "table:gold.acquirer_hourly" },
      { label: "payment_failure_daily", ref: "table:gold.payment_failure_daily" },
    ],
    about: "Materialized views from the pipeline, and acquirer_status, which meridian-acquirer-status rebuilds through a table-update trigger whenever silver.payments changes.",
    evidence: "T06",
  },
  {
    id: "quarantine",
    lane: "lakehouse",
    title: "Quarantine",
    sub: "Failed contract rules",
    kinds: ["build"],
    icon: ShieldAlert,
    ref: "schema:quarantine",
    assets: [
      { label: "payments", ref: "table:quarantine.payments" },
      { label: "customers", ref: "table:quarantine.customers" },
    ],
    about: "Routing compiled from the data contracts: rows that fail a rule land here with the rule's name and severity, instead of reaching silver. meridian-recover can run them again through the current rules.",
    evidence: "T03",
  },
  {
    id: "kb",
    lane: "lakehouse",
    push: true,
    title: "Knowledge base",
    sub: "Documents and chunks",
    kinds: ["build"],
    icon: Database,
    ref: "schema:kb",
    assets: [
      { label: "docs", ref: "table:kb.docs" },
      { label: "chunks_general", ref: "table:kb.chunks_general" },
      { label: "chunks_finance", ref: "table:kb.chunks_finance" },
    ],
    about: "Every document with its version and source, and one chunk table per tier behind that tier's index. Corrections are proposed, approved and audited through procedures.",
    evidence: "T10, T12, T20",
  },

  // AI and agents: platform services
  {
    id: "genie",
    lane: "ai",
    column: 0,
    title: "Genie space",
    sub: "Over the gold tables",
    kinds: ["native"],
    icon: Sparkles,
    ref: "genie",
    about: "The space \"Meridian payments (gold)\": three gold tables with curated example queries and benchmarks, defined as code. Genie writes the SQL and runs it as the person asking.",
    evidence: "T22",
  },
  {
    id: "search",
    lane: "ai",
    column: 0,
    title: "AI Search",
    sub: "{search_endpoint|meridian-search}",
    kinds: ["native", "preview"],
    icon: Search,
    ref: "search",
    assets: [
      { label: "idx_general", ref: "table:kb.idx_general" },
      { label: "idx_finance", ref: "table:kb.idx_finance" },
    ],
    about: "One Delta Sync index per tier, with Databricks-managed embeddings. Row filters don't apply to indexes, so Unity Catalog SELECT on each index decides who can search it. The reranker is PREVIEW.",
    evidence: "T13, T16",
  },
  {
    id: "gateway",
    lane: "ai",
    column: 0,
    title: "Unity Gateway",
    sub: "Claude, as the caller",
    kinds: ["native"],
    icon: Cpu,
    ref: "endpoint:answer",
    assets: [
      { label: "answer model", ref: "endpoint:answer" },
      { label: "embeddings", ref: "endpoint:embedding" },
    ],
    about: "Every model call from the copilot and the knowledge chatbot goes through the gateway as the caller, so usage and limits are per person. The models are serving endpoints named in config/agent.yaml.",
    evidence: "T17, T27",
  },
  {
    id: "mcp",
    lane: "ai",
    column: 0,
    title: "Managed MCP",
    sub: "Search, Genie, SQL",
    kinds: ["preview"],
    icon: Plug,
    ref: "github:examples/claude_code/mcp.json",
    about: "Databricks-managed MCP servers (PREVIEW, and Beta through Unity Gateway) give other agents the same governed tools. Each call carries the person's own token, and Unity Catalog decides it.",
    evidence: "T23, T24",
  },

  // AI and agents: the copilot
  {
    id: "memory",
    lane: "ai",
    column: 1,
    title: "Memory stores",
    sub: "Per-user memory",
    kinds: ["preview", "build"],
    icon: Brain,
    about: "Agent Bricks memory stores (PREVIEW) hold per-user memory. The code, not the model, picks the store and the actor; finance facts are kept as pointers and fetched again as the caller. Managed through the memory API (scripts/setup_memory.py).",
    evidence: "T25",
  },
  {
    id: "copilot",
    lane: "ai",
    column: 1,
    title: "Ops Copilot",
    sub: "Agent Bricks, on Apps",
    kinds: ["build", "preview"],
    icon: Bot,
    ref: "app",
    assets: [{ label: "traces", ref: "experiment" }],
    about: "A Claude tool loop (BUILD) on Agent Bricks' durable agent server (PREVIEW), deployed as this Databricks App: search_kb, ask_genie, start_workflow, run_step, remember and recall. Every tool runs as the caller.",
    evidence: "T17, T26",
  },
  {
    id: "runbook",
    lane: "ai",
    column: 1,
    title: "Governed runbook",
    sub: "RB-014 and its guard",
    kinds: ["build"],
    icon: ShieldCheck,
    ref: "schema:agent",
    assets: [
      { label: "runs", ref: "table:agent.runs" },
      { label: "approvals", ref: "table:agent.approvals" },
      { label: "approve_refund", ref: "fn:agent.approve_refund" },
    ],
    about: "RB-014 runs one step at a time through a guard in code. Impact, the batch, the approval request and the refund are SQL SECURITY DEFINER procedures that re-check their preconditions. Only meridian-admin approves, never the requester.",
    evidence: "T18",
  },

  // Experiences
  {
    id: "console",
    lane: "experience",
    title: "Ops console",
    sub: "This app",
    kinds: ["build"],
    icon: LayoutDashboard,
    ref: "app",
    about: "The Meridian Ops console, this app's browser UI, where Eli works the incident: the overview, the copilot, Genie, the knowledge chatbot and approvals. Every call runs as the person signed in.",
    evidence: "T17",
  },
  {
    id: "dashboard",
    lane: "experience",
    title: "Ops dashboard",
    sub: "Meridian ops, AI/BI",
    kinds: ["native"],
    icon: ChartColumn,
    ref: "dashboard:ops_dashboard",
    about: "The \"Meridian ops\" AI/BI dashboard has five pages: Data products, Jobs and pipeline, Pipeline health, Knowledge, and Copilot. Each viewer queries as themselves, so the market row filter applies.",
    evidence: "T27",
  },
  {
    id: "cli",
    lane: "experience",
    title: "Persona terminal",
    sub: "ask.py, as Ava or Ben",
    kinds: ["build"],
    icon: Terminal,
    ref: "github:scripts/ask.py",
    about: "Ava and Ben are service principals, which can't sign in to the browser. They ask the copilot from a terminal with their own tokens, through the same invocation API.",
    evidence: "T17",
  },
  {
    id: "claude",
    lane: "experience",
    title: "Claude Code",
    sub: "Over managed MCP",
    kinds: ["external"],
    icon: SquareTerminal,
    ref: "github:examples/claude_code",
    about: "Claude Code, and an external agent with no Databricks libraries, call the managed MCP servers with each person's own token, so the same prompts give Ava, Ben and Gus different results.",
    evidence: "T23, T24",
  },

  // Govern and observe
  {
    id: "abac",
    lane: "govern",
    title: "ABAC policies",
    sub: "Masks and row filters",
    kinds: ["native"],
    icon: Lock,
    ref: "catalog",
    assets: [
      { label: "mask_contact", ref: "fn:gov.mask_contact" },
      { label: "in_home_market", ref: "fn:gov.in_home_market" },
    ],
    about: "Policies on the catalog match Data Classification tags (class.*), so they never name a column: contacts masked, identifiers hidden, support limited to its home market. The mask and filter functions are BUILD.",
    evidence: "T04",
  },
  {
    id: "profiling",
    lane: "govern",
    title: "Data profiling",
    sub: "Monitor on silver",
    kinds: ["native", "preview"],
    icon: LineChart,
    ref: "table:silver.payments",
    assets: [
      { label: "profile metrics", ref: "table:obs.payments_profile_metrics" },
      { label: "drift metrics", ref: "table:obs.payments_drift_metrics" },
    ],
    about: "A data profiling monitor on silver.payments writes profile and drift metrics to obs. Anomaly detection (PREVIEW) watches the freshness and completeness of the gold schema.",
    evidence: "T05",
  },
  {
    id: "lineage",
    lane: "govern",
    title: "Lineage and history",
    sub: "Who wrote what",
    kinds: ["native", "build"],
    icon: GitBranch,
    ref: "table:silver.payments",
    assets: [{ label: "lineage_changelog", ref: "table:gov.lineage_changelog" }],
    about: "Delta table history names the job and run behind every write, at once. Unity Catalog lineage gives the blast radius, and a nightly changelog (BUILD) records what changed.",
    evidence: "T06, T06b",
  },
  {
    id: "obs",
    lane: "govern",
    title: "Observability",
    sub: "Event log, releases",
    kinds: ["build"],
    icon: Telescope,
    ref: "schema:obs",
    assets: [
      { label: "v_pipeline_health", ref: "table:obs.v_pipeline_health" },
      { label: "releases", ref: "table:obs.releases" },
    ],
    about: "Views over the pipeline event log and the system tables, the quality events and the release record: one place to ask what failed in the last 24 hours, and why.",
    evidence: "T06b, T21",
  },
  {
    id: "traces",
    lane: "govern",
    title: "MLflow traces",
    sub: "Every copilot run",
    kinds: ["native"],
    icon: ScanSearch,
    ref: "experiment",
    assets: [
      { label: "v_copilot_runs", ref: "table:agent.v_copilot_runs" },
      { label: "spans", ref: "table:agent.copilot_otel_spans" },
    ],
    about: "Every copilot run is traced to an MLflow experiment and to Unity Catalog tables. Views over them feed the dashboard's Copilot page.",
    evidence: "T27",
  },
  {
    id: "system",
    lane: "govern",
    title: "System tables",
    sub: "Audit, billing, usage",
    kinds: ["native"],
    icon: ScrollText,
    ref: "table:obs.v_audit",
    assets: [
      { label: "v_query_history", ref: "table:obs.v_query_history" },
      { label: "v_job_runs", ref: "table:obs.v_job_runs" },
    ],
    about: "Audit, lineage, query history, billing and gateway usage, read through Meridian's views in obs. They are not real-time, so the demo reads events created hours ahead.",
    evidence: "T21, T23, T27",
  },

  // Deliver and operate
  {
    id: "github",
    lane: "deliver",
    title: "GitHub",
    sub: "Holds the code",
    kinds: ["external"],
    icon: FolderGit2,
    ref: "github",
    about: "Holds the code only. Its hosted runners can't reach this workspace, which has an IP access list, so promotion runs inside the workspace.",
    evidence: "T09",
  },
  {
    id: "bundle",
    lane: "deliver",
    title: "Bundle",
    sub: "dev, staging, prod",
    kinds: ["native"],
    icon: Package,
    ref: "folder:prod",
    about: "Every job, pipeline, schema, index and dashboard here is a bundle resource. Developers deploy their own dev copy from a Git folder; only admins deploy staging and prod, which run as the release principal. Opens prod's deployed files.",
    evidence: "T01, T07",
  },
  {
    id: "integration",
    lane: "deliver",
    title: "Integration test",
    sub: "Staging, every defect",
    kinds: ["build"],
    icon: FlaskConical,
    ref: "job:staging/integration_test_job",
    about: "Lands fresh synthetic data, runs a full refresh and the incident batches, then scores every planted defect, and fails on any miss.",
    evidence: "T09",
  },
  {
    id: "postdeploy",
    lane: "deliver",
    title: "Post-deploy",
    sub: "Procedures, release",
    kinds: ["build"],
    icon: Rocket,
    ref: "job:workflow_setup_job",
    assets: [{ label: "releases", ref: "table:obs.releases" }],
    about: "Runs after each deploy: creates the governed workflow and correction procedures, seeds the approved runbooks, and records the release.",
    evidence: "T09, T18",
  },
  {
    id: "recover",
    lane: "deliver",
    title: "Recover",
    sub: "Restore or reprocess",
    kinds: ["build"],
    icon: History,
    ref: "job:restore_table_job",
    assets: [{ label: "bad_backfill.md", ref: "github:docs/runbooks/bad_backfill.md" }],
    about: "A runbook job: restore an ordinary Delta table to a version, or run quarantined rows again through the current rules. Streaming tables can't be restored, so silver is repaired with a targeted refresh.",
    evidence: "T06",
  },
  {
    id: "opsjobs",
    lane: "deliver",
    title: "Operations jobs",
    sub: "Daily, reset, fault",
    kinds: ["build"],
    icon: CalendarClock,
    ref: "job:export_logs_job",
    assets: [
      { label: "demo-reset", ref: "job:demo_reset_job" },
      { label: "backfill", ref: "job:bad_backfill_job" },
    ],
    about: "meridian-daily refreshes the views and exports logs and audit files at 00:30 SGT. The demo reset rewrites data and never drops a table. The backfill job is the fault planted for scene 3.",
    evidence: "T06b, T29",
  },
];

export const EDGES: ArchEdge[] = [
  // The data lifecycle
  { from: "files", to: "ingest", kind: "trigger", label: "file arrival" },
  { from: "ingest", to: "pipeline", kind: "trigger", label: "runs" },
  { from: "pipeline", to: "checks", kind: "trigger", label: "then" },
  { from: "checks", to: "digest", kind: "trigger", label: "then" },
  { from: "pipeline", to: "bronze", kind: "data", label: "Auto Loader" },
  { from: "bronze", to: "silver", kind: "data" },
  { from: "silver", to: "gold", kind: "data" },
  { from: "pipeline", to: "quarantine", kind: "data", label: "failed rules" },
  { from: "kbfiles", to: "kbsync", kind: "trigger", label: "file arrival" },
  { from: "slack", to: "kbsync", kind: "data" },
  { from: "kbsync", to: "kb", kind: "data" },
  { from: "kb", to: "search", kind: "data", label: "Delta Sync" },
  { from: "gold", to: "genie", kind: "data" },
  { from: "genie", to: "copilot", kind: "ai", label: "ask_genie" },
  { from: "search", to: "copilot", kind: "ai", label: "search_kb" },
  { from: "gateway", to: "copilot", kind: "ai", label: "model calls" },
  { from: "memory", to: "copilot", kind: "ai", label: "recall" },
  { from: "copilot", to: "runbook", kind: "control", label: "run_step" },
  { from: "copilot", to: "console", kind: "data", label: "answers" },
  { from: "copilot", to: "cli", kind: "data", label: "answers" },
  { from: "runbook", to: "console", kind: "control", label: "approvals" },
  { from: "mcp", to: "claude", kind: "ai", label: "tools" },
  { from: "github", to: "bundle", kind: "deliver", label: "Git folder" },
  { from: "bundle", to: "integration", kind: "deliver", label: "staging" },
  { from: "integration", to: "postdeploy", kind: "deliver", label: "then prod" },

  // Drawn when one of their boxes is in focus
  { from: "quarantine", to: "digest", kind: "data", label: "grouped by rule", quiet: true },
  { from: "digest", to: "gateway", kind: "ai", label: "ai_query", quiet: true },
  { from: "checks", to: "obs", kind: "data", label: "events", quiet: true },
  { from: "digest", to: "obs", kind: "data", label: "dq_digest", quiet: true },
  { from: "silver", to: "profiling", kind: "data", label: "monitored", quiet: true },
  { from: "abac", to: "silver", kind: "governs", label: "masks, row filter", quiet: true },
  { from: "silver", to: "lineage", kind: "data", label: "history", quiet: true },
  { from: "gold", to: "console", kind: "data", label: "Overview", quiet: true },
  { from: "genie", to: "console", kind: "ai", label: "Genie page", quiet: true },
  { from: "search", to: "console", kind: "ai", label: "Knowledge page", quiet: true },
  { from: "gateway", to: "console", kind: "ai", label: "Knowledge page", quiet: true },
  { from: "search", to: "mcp", kind: "ai", quiet: true },
  { from: "genie", to: "mcp", kind: "ai", quiet: true },
  { from: "gold", to: "dashboard", kind: "data", quiet: true },
  { from: "obs", to: "dashboard", kind: "data", quiet: true },
  { from: "traces", to: "dashboard", kind: "data", label: "Copilot page", quiet: true },
  { from: "kb", to: "dashboard", kind: "data", quiet: true },
  { from: "copilot", to: "traces", kind: "data", label: "traces", quiet: true },
  { from: "claude", to: "system", kind: "data", label: "audit rows", quiet: true },
  { from: "gateway", to: "system", kind: "data", label: "usage", quiet: true },
  { from: "postdeploy", to: "runbook", kind: "deliver", label: "procedures", quiet: true },
  { from: "postdeploy", to: "obs", kind: "deliver", label: "release", quiet: true },
  { from: "recover", to: "gold", kind: "control", label: "restore", quiet: true },
  { from: "recover", to: "silver", kind: "control", label: "targeted refresh", quiet: true },
  { from: "opsjobs", to: "silver", kind: "control", label: "planted backfill", quiet: true },
  { from: "opsjobs", to: "obs", kind: "data", label: "exports", quiet: true },
];

// The run of show's scenes as paths through the architecture (docs/run_of_show.md).
export const FLOWS: Flow[] = [
  {
    id: "detect",
    scene: "1",
    title: "Detect",
    steps: [
      { node: "files", title: "A file lands", text: "An incident file lands in the volume's payments/ folder, and its file-arrival trigger starts meridian-ingest." },
      { node: "ingest", title: "One run", text: "A single job run holds the pipeline update, the quality checks, the escalation and the AI digest." },
      { node: "pipeline", title: "Expectations", text: "Auto Loader reads the file into bronze, and expectations compiled from the data contracts check every row." },
      { node: "quarantine", title: "Quarantine", text: "Rows that break a rule go to quarantine with the rule's name and severity, instead of reaching silver." },
      { node: "silver", title: "Silver", text: "Valid rows reach silver, deduplicated, with masks and the market row filter applied to every reader." },
      { node: "gold", title: "Gold", text: "Gold summarizes failures per acquirer, and acq_7 shows as degraded against its 14-day baseline." },
      { node: "checks", title: "Checks", text: "Drift flags acq_7, freshness flags the arrival gap, and PII coverage flags an untagged column. Each breach sends an email." },
      { node: "digest", title: "AI digest", text: "ai_query summarizes the quarantine rule by rule. Counts come from SQL; the text is flagged AI-generated and not reviewed." },
      { node: "dashboard", title: "Dashboard", text: "The Pipeline health page shows the degraded acquirer first, then the issues of the last 14 days." },
    ],
  },
  {
    id: "protect",
    scene: "2",
    title: "Protect",
    steps: [
      { node: "abac", title: "Policies", text: "Data Classification tags mark the sensitive columns, and the ABAC policies on the catalog match the tags, never column names." },
      { node: "silver", title: "Masks and filters", text: "Contacts are masked, identifiers hidden, and support sees its home market only. Admins and the pipeline's principal see raw values." },
      { node: "dashboard", title: "Dashboard", text: "The dashboard queries as each viewer, so the same chart shows Ava fewer rows than Eli." },
      { node: "genie", title: "Genie", text: "Genie runs its SQL as the person asking, so the same policies apply to every answer." },
    ],
  },
  {
    id: "rootcause",
    scene: "3",
    title: "Root cause",
    steps: [
      { node: "opsjobs", title: "A bad write", text: "meridian-backfill-fx-correction, the planted fault, rewrites a day of silver.payments with a wrong FX correction." },
      { node: "silver", title: "Table history", text: "silver.payments' history names the job and run behind each version, at once." },
      { node: "lineage", title: "Blast radius", text: "Lineage shows every job and table that reads silver.payments." },
      { node: "gold", title: "Downstream", text: "gold.acquirer_status was rebuilt from the bad rows by its table-update trigger." },
      { node: "recover", title: "Recover", text: "meridian-recover restores gold to its last good version, and silver is repaired with a targeted refresh from bronze." },
    ],
  },
  {
    id: "ship",
    scene: "4",
    title: "Ship a fix",
    steps: [
      { node: "github", title: "A branch", text: "A developer pushes a branch and opens a pull request. GitHub holds the code only." },
      { node: "bundle", title: "Dev copy", text: "In their Git folder, they deploy their own dev copy of every job and pipeline from the bundle UI." },
      { node: "integration", title: "Staging test", text: "On staging, the integration test lands fresh data and scores every planted defect: a rule-weakening branch fails, main passes." },
      { node: "bundle", title: "Prod", text: "Only admins deploy main to prod, from a Git folder. Prod runs as the release principal." },
      { node: "postdeploy", title: "Release", text: "meridian-post-deploy creates the governed procedures and records the release in obs.releases." },
    ],
  },
  {
    id: "runbook",
    scene: "5",
    title: "Run RB-014",
    steps: [
      { node: "cli", title: "Ben asks", text: "Ben, in the terminal: \"acq_7 is degraded. Run RB-014 for acq_7 over the last 24 hours.\"" },
      { node: "copilot", title: "The copilot", text: "The copilot starts a run of the approved RB-014 version. Every tool call runs as Ben." },
      { node: "genie", title: "s1: data", text: "Genie answers the payment questions with SQL that runs under Ben's grants." },
      { node: "search", title: "s2: the SLA clause", text: "The SLA clause comes from the finance-tier index, which Ben can search and Ava cannot. Ava's run stops here." },
      { node: "runbook", title: "s3 to s5", text: "Impact, the refund batch and the approval request run as definer procedures that re-check every precondition." },
      { node: "console", title: "Approve", text: "Eli approves the batch on the console's Approvals page, through agent.approve_refund. The requester can't approve." },
      { node: "runbook", title: "s6: refund", text: "Ben continues, and s6 executes the batch. The guard refuses any step out of order." },
      { node: "traces", title: "Traced", text: "Every step and tool call is traced, and the dashboard's Copilot page reads the traces as tables." },
    ],
  },
  {
    id: "knowledge",
    scene: "5",
    title: "Cited answer",
    steps: [
      { node: "kbfiles", title: "Sources", text: "Runbooks, policies and fee schedules land by tier, and Slack history arrives as an export." },
      { node: "kbsync", title: "Sync", text: "Knowledge sync updates only the documents that changed. The 10-minute sweep catches edits and deletes." },
      { node: "kb", title: "Chunks", text: "Each document is chunked into its tier's table, with its version and source." },
      { node: "search", title: "Search", text: "Hybrid search over the tiers the asker can read, then the reranker. Below the threshold, it abstains." },
      { node: "gateway", title: "Answer", text: "Claude answers from the passages only, through Unity Gateway as the asker, and cites each one." },
      { node: "console", title: "Knowledge page", text: "The console's Knowledge page shows the answer, its citations and the passages behind them." },
    ],
  },
  {
    id: "mcp",
    scene: "6",
    title: "Claude Code",
    steps: [
      { node: "claude", title: "Same prompts", text: "Ava, Ben and Gus run the same prompts in Claude Code, each with their own token." },
      { node: "mcp", title: "Managed MCP", text: "Managed MCP servers expose AI Search, Genie and Databricks SQL as tools." },
      { node: "search", title: "Refused", text: "Unity Catalog decides each call: Ava's search of the finance index is refused." },
      { node: "genie", title: "As each person", text: "Genie and SQL answer as each person, so the results differ." },
      { node: "system", title: "Audit", text: "Each call lands in the audit log and in gateway usage, one row per person." },
    ],
  },
  {
    id: "memory",
    scene: "6",
    title: "Memory",
    steps: [
      { node: "cli", title: "Ben saves a fact", text: "Ben asks the copilot to remember acq_2's bank transfer fee, which came from a finance document." },
      { node: "copilot", title: "The code decides", text: "The code, not the model, picks the store and the actor: the fact came from a finance passage." },
      { node: "memory", title: "A pointer", text: "mem-finance keeps a pointer to the document and page, never the fee itself." },
      { node: "search", title: "Fetched again", text: "At recall, the passage is fetched again from the finance index as the caller, so Ava gets nothing." },
    ],
  },
  {
    id: "trust",
    scene: "7",
    title: "Trust and cost",
    steps: [
      { node: "traces", title: "Traces", text: "Copilot traces land in an MLflow experiment and in Unity Catalog tables." },
      { node: "dashboard", title: "Copilot page", text: "The dashboard's Copilot page shows runs by caller, the slowest tools, refusals and denials." },
      { node: "gateway", title: "Caching", text: "The system prompt and tools are cached on the gateway path; T27 measured the saving at list price." },
      { node: "system", title: "Cost", text: "Billing and gateway usage give the POC's own cost, by resource and by person." },
      { node: "obs", title: "Audit export", text: "meridian-daily writes dated audit and log files to the exports volume." },
    ],
  },
];
