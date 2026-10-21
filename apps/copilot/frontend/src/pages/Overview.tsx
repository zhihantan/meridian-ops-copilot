import clsx from "clsx";
import { ArrowRight, BookOpen, Database, Hourglass, LayoutDashboard, RefreshCw, Sparkles, TriangleAlert, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, problem } from "../api";
import { Badge, Button, Card, ErrorNote, PageHeader, Pill } from "../components/ui";
import type { Acquirer, Me, Page, PendingApproval } from "../types";
import { money, pct } from "../util";

// The landing page: acquirer status from gold.acquirer_status (NATIVE Unity Catalog table; the status rule is the
// pipeline's), read with the visitor's own grants, and the three ways to work the incident.

const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
};

function AcquirerCard({ a }: { a: Acquirer }) {
  const recent = Number(a.recent_failure_rate);
  const base = Number(a.baseline_failure_rate);
  const ratio = base > 0 ? recent / base : 0;
  const degraded = a.status === "degraded";
  const scale = Math.max(recent, base * 3, 0.0001);
  return (
    <Card className={clsx("p-4", degraded && "border-bad/40 ring-1 ring-bad/20")}>
      <div className="flex items-center justify-between">
        <span className="font-mono text-[13px] font-semibold">{a.acquirer_id}</span>
        <Pill tone={degraded ? "bad" : "ok"}>{degraded ? "degraded" : "normal"}</Pill>
      </div>
      <p className={clsx("mt-3 text-[28px] font-semibold tracking-tight tabular-nums", degraded ? "text-bad" : "text-ink")}>{pct(recent)}</p>
      <p className="text-[12.5px] text-muted">
        failing in the last 6 hours · baseline {pct(base)}
        {ratio >= 1.5 ? ` · ${ratio.toFixed(1)}×` : ""}
      </p>
      <div className="relative mt-3 h-2 rounded-full bg-black/5" title="Recent failure rate against the 14-day baseline; degraded above 3 times the baseline">
        <div className={clsx("h-2 rounded-full", degraded ? "bg-bad" : "bg-ok")} style={{ width: `${Math.min(1, recent / scale) * 100}%` }} />
        <div className="absolute -top-1 h-4 w-0.5 rounded bg-navy-900/60" style={{ left: `${Math.min(1, (base * 3) / scale) * 100}%` }} />
      </div>
      <p className="mt-2 text-[12px] text-muted">SGD {money(a.recent_amount)} in 6 hours · {money(a.baseline_daily_amount)} a day usually</p>
    </Card>
  );
}

function Start({ icon: Icon, tone, title, text, question, onClick }: { icon: LucideIcon; tone: string; title: string; text: string; question: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group rounded-2xl border border-line bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-navy-700/40 hover:shadow-md">
      <span className={clsx("grid size-10 place-items-center rounded-xl text-white", tone)}>
        <Icon className="size-5" />
      </span>
      <p className="mt-3 text-[15px] font-semibold">{title}</p>
      <p className="mt-1 text-[13px] text-muted">{text}</p>
      <p className="mt-3 flex items-start gap-1.5 text-[13px] font-medium text-info">
        <ArrowRight className="mt-0.5 size-4 shrink-0 transition group-hover:translate-x-0.5" />
        <span>“{question}”</span>
      </p>
    </button>
  );
}

export default function OverviewPage({ me, pending, onAsk, navigate }: { me: Me | null; pending: PendingApproval[] | null; onAsk: (page: Page, question: string) => void; navigate: (page: Page) => void }) {
  const [rows, setRows] = useState<Acquirer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      const r = await api<{ acquirers: Acquirer[]; error?: string | null }>("/api/overview");
      setRows(r.acquirers);
      setError(r.error ?? null);
    } catch (e) {
      setError(problem(e));
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const degraded = rows?.filter((a) => a.status === "degraded") ?? [];
  const first = degraded[0];
  const until = rows?.[0]?.data_until_sgt;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={LayoutDashboard}
        title="Overview"
        subtitle="Acquirer health from the governed gold tables, as you can see them"
        badges={<Badge kind="native">Unity Catalog gold tables</Badge>}
        actions={<Button icon={RefreshCw} onClick={refresh}>Refresh</Button>}
      />
      <div className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-6xl space-y-6">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">{greeting()}</h2>
            <p className="mt-1 text-[14px] text-muted">
              Synthetic payments in five markets through seven acquirers{until ? `; the data runs until ${until} SGT` : ""}.
            </p>
          </div>

          {first ? (
            <div className="rise flex flex-wrap items-center gap-4 rounded-2xl border border-bad/30 bg-gradient-to-r from-bad-soft to-white p-5">
              <span className="grid size-11 place-items-center rounded-xl bg-bad text-white shadow-md shadow-bad/30">
                <TriangleAlert className="size-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[16px] font-semibold">
                  {first.acquirer_id} is degraded: {pct(first.recent_failure_rate)} of payments failing, against a {pct(first.baseline_failure_rate)} baseline
                </p>
                <p className="text-[13px] text-muted">
                  {(Number(first.recent_failure_rate) / Number(first.baseline_failure_rate)).toFixed(1)} times its usual rate. Degraded means more than 3 times the 14-day baseline over the last 6 hours.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" icon={Sparkles} onClick={() => onAsk("copilot", "Which acquirers are degraded right now, and which runbook should we follow?")}>
                  Work it with the copilot
                </Button>
                <Button icon={Database} onClick={() => onAsk("genie", `Daily failure rate for ${first.acquirer_id} over the last 14 days`)}>
                  Chart it in Genie
                </Button>
              </div>
            </div>
          ) : null}
          {error ? <ErrorNote>{error}</ErrorNote> : null}

          <section>
            <h3 className="mb-3 text-[15px] font-semibold">Acquirers</h3>
            {!rows && !error ? <p className="text-[13.5px] text-muted">Loading from the gold tables…</p> : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {rows?.map((a) => (
                <AcquirerCard key={a.acquirer_id} a={a} />
              ))}
            </div>
          </section>

          <section className="grid gap-3 lg:grid-cols-3">
            <Start icon={Sparkles} tone="bg-brand" title="Ops Copilot" text="Follows the approved runbook step by step, cites Genie and the knowledge base, and stops for a human." question="How much in refundable failed payments has acq_7 caused in the last 24 hours, and does a refund batch that size need approval?" onClick={() => onAsk("copilot", "How much in refundable failed payments has acq_7 caused in the last 24 hours, and does a refund batch that size need approval?")} />
            <Start icon={Database} tone="bg-info" title="Genie" text="Plain-English questions over the gold tables, with the SQL, the rows and a chart." question="Hourly payments and failures for acq_7 in the last 24 hours" onClick={() => onAsk("genie", "Hourly payments and failures for acq_7 in the last 24 hours")} />
            <Start icon={BookOpen} tone="bg-violet" title="Knowledge" text="Policies, runbooks, fees and SLAs from the tiers you can read, every sentence cited." question="Which failure codes make a failed payment eligible for a refund?" onClick={() => onAsk("knowledge", "Which failure codes make a failed payment eligible for a refund?")} />
          </section>

          {me?.admin ? (
            <Card className="flex flex-wrap items-center gap-4 p-5">
              <span className="grid size-10 place-items-center rounded-xl bg-warn-soft text-[#8A5A00]">
                <Hourglass className="size-5" />
              </span>
              <div className="flex-1">
                <p className="font-semibold">{pending?.length ? `${pending.length} refund batch${pending.length === 1 ? "" : "es"} waiting for your approval` : "No refund batch is waiting for approval"}</p>
                <p className="text-[13px] text-muted">A runbook run stops at s5 for any batch above SGD 500, until an admin who is not the requester approves it.</p>
              </div>
              <Button icon={ArrowRight} onClick={() => navigate("approvals")}>
                Approvals
              </Button>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
