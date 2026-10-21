import clsx from "clsx";
import { BookOpen, Database, LayoutDashboard, ShieldCheck, Sparkles, type LucideIcon } from "lucide-react";

import type { Me, Page } from "../types";
import { initials } from "../util";
import { Avatar, Tier } from "./ui";

const NAV: { page: Page; label: string; icon: LucideIcon; hint: string }[] = [
  { page: "overview", label: "Overview", icon: LayoutDashboard, hint: "Acquirer health" },
  { page: "copilot", label: "Ops Copilot", icon: Sparkles, hint: "Runbooks and refunds" },
  { page: "genie", label: "Genie", icon: Database, hint: "Ask the data" },
  { page: "knowledge", label: "Knowledge", icon: BookOpen, hint: "Ask the policies" },
  { page: "approvals", label: "Approvals", icon: ShieldCheck, hint: "Refund batches" },
];

export function Sidebar({ page, navigate, me, meError, pendingCount }: { page: Page; navigate: (p: Page) => void; me: Me | null; meError: string | null; pendingCount: number }) {
  return (
    <aside className="flex w-[264px] shrink-0 flex-col bg-navy-900 text-white">
      <div className="flex items-center gap-3 px-5 pb-6 pt-5">
        <span className="grid size-9 place-items-center rounded-xl bg-brand shadow-lg shadow-brand/30">
          <Sparkles className="size-5" />
        </span>
        <div>
          <p className="text-[15px] font-semibold leading-tight">Meridian Ops</p>
          <p className="text-[12px] text-white/60">Incident console · synthetic data</p>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3">
        {NAV.map((n) => {
          const active = page === n.page;
          return (
            <button
              key={n.page}
              type="button"
              onClick={() => navigate(n.page)}
              className={clsx("relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition", active ? "bg-white/12 text-white" : "text-white/70 hover:bg-white/6 hover:text-white")}
            >
              {active ? <span className="absolute left-0 top-2 bottom-2 w-1 rounded-r bg-brand" /> : null}
              <n.icon className="size-[18px]" />
              <span className="flex-1">
                <span className="block text-[14px] font-medium leading-tight">{n.label}</span>
                <span className="block text-[11.5px] text-white/50">{n.hint}</span>
              </span>
              {n.page === "approvals" && pendingCount > 0 ? <span className="rounded-full bg-warn px-2 py-0.5 text-[11px] font-bold text-navy-900">{pendingCount}</span> : null}
            </button>
          );
        })}
      </nav>
      <div className="m-3 rounded-2xl bg-white/6 p-4">
        {me ? (
          <>
            <div className="flex items-center gap-3">
              <Avatar text={initials(me.name)} />
              <div className="min-w-0">
                <p className="truncate text-[14px] font-semibold">{me.name}</p>
                <p className="text-[12px] text-white/60">{me.admin ? "meridian-admin · approves refunds" : "Not an approver"}</p>
              </div>
            </div>
            <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-white/50">Knowledge you can read</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">{me.tiers.length ? me.tiers.map((t) => <Tier key={t} name={t} />) : <span className="text-[12px] text-white/60">none</span>}</div>
            <p className="mt-3 text-[11.5px] leading-snug text-white/55">Everything here runs as you: Genie, the knowledge base and the runbook procedures check your own permissions.</p>
          </>
        ) : (
          <p className="text-[12.5px] text-white/70">{meError ?? "Checking who you are…"}</p>
        )}
      </div>
      <div className="flex items-center justify-between px-5 pb-4 text-[11.5px] text-white/45">
        <span>BUILD · this console</span>
        <a href="/classic" className="underline-offset-2 hover:text-white/80 hover:underline">
          Classic page
        </a>
      </div>
    </aside>
  );
}
