import clsx from "clsx";
import { Bookmark, BookOpen, Check, Clock, Copy, Database, Plus, Sparkles, Workflow, X, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, post, problem, readSSE, sleep } from "../api";
import { Composer } from "../components/Composer";
import { Citation, Markdown } from "../components/Markdown";
import { Badge, BotCard, Button, ErrorNote, PageHeader, Spinner, type Suggestion, UserBubble, Welcome } from "../components/ui";
import type { Incoming } from "../types";
import { citations, count, money, uid, useNow, useSessionState } from "../util";

// The copilot (T17) runs on Agent Bricks' managed runtime: a question is one background invocation, and its
// event stream reports each tool call, each tool result (labels and statuses only) and the answer.

type StepState = "running" | "done" | "bad" | "wait";
interface ToolStep { tool: string; label: string; detail: string; t0: number; t1?: number; state: StepState; result?: string }
type RunState = "todo" | "done" | "bad" | "wait" | "stop";
interface RunStep { id: string; name: string; state: RunState; note: string }
interface Run { workflow?: string; title?: string; steps: RunStep[]; next?: string | null; stopped?: string }
interface Turn {
  id: string;
  question: string;
  started: number;
  status: "running" | "done" | "error";
  phase: string;
  steps: ToolStep[];
  runIds: string[];
  answer: string;
  error?: string;
  seconds?: number;
  urls?: { status: string; events: string };
}
interface State { session: string; history: { role: "user" | "assistant"; content: string }[]; turns: Turn[]; runs: Record<string, Run> }

const TOOLS: Record<string, [string, LucideIcon]> = {
  search_kb: ["Searching the knowledge base", BookOpen],
  ask_genie: ["Asking Genie", Database],
  start_workflow: ["Starting the runbook", Workflow],
  run_step: ["Running a runbook step", Workflow],
  remember: ["Saving a memory", Bookmark],
  recall: ["Checking memory", Bookmark],
};

const SUGGESTIONS: Suggestion[] = [
  { kind: "Data and runbook", question: "Which acquirers are degraded right now, and which runbook should we follow?" },
  { kind: "Data and policy", question: "How much in refundable failed payments has acq_7 caused in the last 24 hours, and does a refund batch that size need approval?" },
  { kind: "Runbook", question: "Which step of RB-014 computes the customer impact?" },
  { kind: "Policy", question: "How long does a refund approval stay valid?" },
];

const fresh = (): State => ({ session: uid(), history: [], turns: [], runs: {} });

type Summary = Record<string, any>;

function resultText(s: Summary): string {
  const parts: string[] = [];
  if (s.workflow && s.steps) parts.push(`${s.workflow}, ${s.steps.length} steps, starting at ${s.next_step}`);
  if (s.step) parts.push(`step ${s.step}${s.status ? ` ${s.status}` : ""}`);
  for (const k of ["refused", "stopped"]) if (s[k]) parts.push(typeof s[k] === "string" ? `${k}: ${s[k]}` : k);
  if (s.approval_id) parts.push(`approval ${s.approval_id}`);
  if (s.payments != null) parts.push(`${count(s.payments)} payments`);
  if (s.total_sgd != null) parts.push(`SGD ${money(s.total_sgd)}`);
  const sources: string[] = (s.sources ?? []).map((x: string) => x.replace(/^\[|\]$/g, ""));
  if (sources.length) parts.push(`${sources.length} source${sources.length > 1 ? "s" : ""}: ${sources.slice(0, 5).join(", ")}${sources.length > 5 ? ", …" : ""}`);
  if (s.note) parts.push(String(s.note).slice(0, 160));
  return parts.join(" · ") || "done";
}

function stepState(s: Summary): [RunState, string] {
  const facts = [s.payments != null ? `${count(s.payments)} payments` : "", s.total_sgd != null ? `SGD ${money(s.total_sgd)}` : ""].filter(Boolean).join(" · ");
  if (s.refused) return ["bad", `refused: ${s.refused}`];
  if (s.error) return ["bad", String(s.error)];
  if (s.status === "not_entitled") return ["bad", s.stopped || "not entitled"];
  if (s.status === "failed") return ["bad", s.note || "failed"];
  if (s.status === "no_incident") return ["stop", s.stopped || "no incident"];
  if (s.status === "pending") return ["wait", ["waiting for approval", s.approval_id, facts].filter(Boolean).join(" · ")];
  return ["done", [s.status !== "ok" ? s.status : "", facts].filter(Boolean).join(" · ")];
}

const editTurn = (s: State, id: string, fn: (t: Turn) => Turn): State => ({ ...s, turns: s.turns.map((t) => (t.id === id ? fn(t) : t)) });

function onMessage(s: State, id: string, m: any, t: number): State {
  if (m.role === "tool") {
    let summary: Summary = {};
    try {
      summary = JSON.parse(m.content || "{}");
    } catch {
      /* not a summary */
    }
    const bad = Boolean(summary.refused || summary.error || ["not_entitled", "failed"].includes(summary.status));
    const wait = summary.status === "pending";
    let next = editTurn(s, id, (turn) => {
      const i = turn.steps.findIndex((st) => st.tool === m.name && st.state === "running");
      const steps = turn.steps.slice();
      if (i >= 0) steps[i] = { ...steps[i], t1: t, state: bad ? "bad" : wait ? "wait" : "done", result: resultText(summary) };
      const runIds = summary.run_id && !turn.runIds.includes(summary.run_id) ? [...turn.runIds, summary.run_id] : turn.runIds;
      return { ...turn, steps, runIds, phase: "Thinking…" };
    });
    if (summary.run_id) {
      const run: Run = { ...(next.runs[summary.run_id] ?? { steps: [] }) };
      if (summary.steps) run.steps = summary.steps.map((x: { id: string; name: string }) => ({ id: x.id, name: x.name, state: "todo" as RunState, note: "" }));
      if (summary.workflow) run.workflow = summary.workflow;
      if (summary.title) run.title = summary.title;
      if (summary.step) {
        const steps = run.steps.slice();
        let i = steps.findIndex((x) => x.id === summary.step);
        if (i < 0) {
          steps.push({ id: summary.step, name: "", state: "todo", note: "" });
          i = steps.length - 1;
        }
        const [state, note] = stepState(summary);
        steps[i] = { ...steps[i], name: summary.name || steps[i].name, state, note };
        run.steps = steps;
      }
      if ("next_step" in summary) run.next = summary.next_step;
      if (summary.stopped) run.stopped = summary.stopped;
      next = { ...next, runs: { ...next.runs, [summary.run_id]: run } };
    }
    return next;
  }
  if (m.tool_calls?.length) {
    return editTurn(s, id, (turn) => {
      const added = m.tool_calls.map((c: { name: string; args?: Record<string, unknown> }) => {
        const args = c.args ?? {};
        let label = (TOOLS[c.name] ?? [c.name])[0];
        if (c.name === "run_step" && args.step_id) label = `Running runbook step ${args.step_id}`;
        const detail = String(Object.values(args).find((v) => typeof v === "string") ?? "");
        return { tool: c.name, label, detail, t0: t, state: "running" as StepState };
      });
      return { ...turn, steps: [...turn.steps, ...added], phase: `${added[added.length - 1].label}…` };
    });
  }
  if (m.content) return editTurn(s, id, (turn) => ({ ...turn, answer: m.content, phase: "Writing the answer…" }));
  return s;
}

function Elapsed({ since }: { since: number }) {
  const now = useNow(true);
  return <span className="ml-auto tabular-nums text-muted">{Math.max(0, Math.floor((now - since) / 1000))} s</span>;
}

function StateIcon({ state }: { state: StepState }) {
  if (state === "running") return <Spinner className="size-3.5 text-info" />;
  if (state === "bad") return <X className="size-3.5 text-bad" strokeWidth={3} />;
  if (state === "wait") return <Clock className="size-3.5 text-[#B7791F]" strokeWidth={2.5} />;
  return <Check className="size-3.5 text-ok" strokeWidth={3} />;
}

function Timeline({ steps }: { steps: ToolStep[] }) {
  if (!steps.length) return null;
  return (
    <ol className="relative mb-4 space-y-3 before:absolute before:bottom-2 before:left-[11px] before:top-2 before:w-px before:bg-line">
      {steps.map((st, i) => {
        const Icon = (TOOLS[st.tool] ?? [st.tool, Workflow])[1];
        return (
          <li key={i} className="relative flex gap-3">
            <span className="z-10 mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border border-line bg-white">
              <StateIcon state={st.state} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13.5px] font-medium">
                <Icon className="size-4 text-muted" aria-hidden />
                {st.label}
                {st.t1 !== undefined ? <span className="text-[12px] font-normal text-muted">{Math.max(0, st.t1 - st.t0).toFixed(1)} s</span> : null}
              </div>
              {st.detail ? <div className="truncate text-[13px] italic text-muted">“{st.detail}”</div> : null}
              {st.result ? <div className="text-[12.5px] text-muted">{st.result}</div> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function RunCard({ id, run }: { id: string; run: Run }) {
  const label = [run.workflow, run.title].filter(Boolean).join(" · ") || "Runbook run";
  return (
    <div className="mb-4 rounded-2xl border border-line bg-paper/60 p-4">
      <div className="mb-3 flex items-center gap-2 text-[13.5px]">
        <Workflow className="size-4 text-navy-700" aria-hidden />
        <strong className="font-semibold">{label}</strong>
        <span className="ml-auto font-mono text-[11.5px] text-muted">{id}</span>
      </div>
      <ol className="grid gap-2">
        {run.steps.map((st) => (
          <li key={st.id} className="grid grid-cols-[22px_34px_1fr] items-start gap-x-2 text-[13px]">
            <span
              className={clsx(
                "mt-0.5 grid size-5 place-items-center rounded-full border-2",
                st.state === "done" && "border-ok bg-ok text-white",
                st.state === "wait" && "border-warn bg-warn text-navy-900",
                st.state === "bad" && "border-bad bg-bad text-white",
                st.state === "stop" && "border-[#CBD5D9] bg-[#CBD5D9]",
                st.state === "todo" && (run.next === st.id ? "border-info bg-white" : "border-[#CBD5D9] bg-white"),
              )}
            >
              {st.state === "done" ? <Check className="size-3" strokeWidth={3.5} /> : null}
              {st.state === "wait" ? <Clock className="size-3" strokeWidth={3} /> : null}
              {st.state === "bad" ? <X className="size-3" strokeWidth={3.5} /> : null}
            </span>
            <span className="font-semibold">{st.id}</span>
            <span className={clsx(st.state === "todo" ? "text-muted" : "text-ink")}>
              {st.name}
              {st.note ? <span className="block text-[12px] text-muted">{st.note}</span> : null}
            </span>
          </li>
        ))}
      </ol>
      {run.stopped ? <p className="mt-3 text-[13px] font-medium text-bad">Run stopped: {run.stopped}</p> : null}
    </div>
  );
}

function TurnView({ turn, runs }: { turn: Turn; runs: Record<string, Run> }) {
  const [copied, setCopied] = useState(false);
  const cites = citations(turn.answer);
  return (
    <>
      <UserBubble text={turn.question} />
      <BotCard icon={Sparkles}>
        <Timeline steps={turn.steps} />
        {turn.runIds.map((rid) => (runs[rid] ? <RunCard key={rid} id={rid} run={runs[rid]} /> : null))}
        {turn.status === "running" ? (
          <div className="flex items-center gap-2 text-[13.5px] text-muted">
            <Spinner />
            <span>{turn.phase}</span>
            <Elapsed since={turn.started} />
          </div>
        ) : null}
        {turn.status === "error" ? <ErrorNote>{turn.error}</ErrorNote> : null}
        {turn.status === "done" ? (
          <>
            <Markdown text={turn.answer || "No answer was returned."} />
            {cites.length ? (
              <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
                <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Sources</span>
                {cites.map((c) => (
                  <Citation key={c} label={c} />
                ))}
              </div>
            ) : null}
            <div className="mt-3 flex items-center gap-3 text-[12.5px] text-muted">
              <span>
                {turn.seconds} s · {turn.steps.length} tool call{turn.steps.length === 1 ? "" : "s"}
              </span>
              <Button
                variant="ghost"
                icon={copied ? Check : Copy}
                className="ml-auto"
                onClick={async () => {
                  await navigator.clipboard.writeText(turn.answer);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </>
        ) : null}
      </BotCard>
    </>
  );
}

export default function CopilotPage({ incoming }: { incoming: Incoming | null }) {
  const [state, setState] = useSessionState<State>("meridian.copilot", fresh);
  const live = useRef(state);
  live.current = state;
  const scroller = useRef<HTMLDivElement>(null);
  const busy = state.turns.some((t) => t.status === "running");

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [state.turns]);

  const follow = useCallback(
    async (id: string, started: number, question: string, urls: { status: string; events: string }, session: string) => {
      const t = () => (Date.now() - started) / 1000;
      let after = 0;
      let st: any = { status: "running" };
      try {
        while (!["completed", "failed"].includes(st.status)) {
          try {
            const resp = await fetch(`${urls.events}?after=${after}`, { credentials: "same-origin", headers: { "X-Routing-Key": session } });
            if (resp.ok) after = (await readSSE(resp, (_name, ev) => ev?.type === "message" && ev.message && setState((s) => onMessage(s, id, ev.message, t())), after)) ?? after;
          } catch {
            /* a dropped stream resumes from the last event id */
          }
          st = await api<any>(urls.status, { headers: { "X-Routing-Key": session } });
          if (!["completed", "failed"].includes(st.status)) await sleep(1500);
        }
        if (st.status === "failed") throw new Error(typeof st.error === "string" ? st.error : (st.error?.message ?? "The copilot could not answer."));
        const out = st.output ?? {};
        const messages: any[] = (Array.isArray(out) ? out : out.output) ?? [];
        const fallback = [...messages].reverse().find((m) => m.role === "assistant" && m.content)?.content ?? "";
        setState((s) => {
          const turn = s.turns.find((x) => x.id === id);
          const answer = turn?.answer || fallback;
          const next = editTurn(s, id, (x) => ({ ...x, status: "done", answer, seconds: Math.round(t()) }));
          return answer ? { ...next, history: [...next.history, { role: "user", content: question }, { role: "assistant", content: answer }] } : next;
        });
      } catch (e) {
        setState((s) => editTurn(s, id, (x) => ({ ...x, status: "error", error: problem(e), seconds: Math.round(t()) })));
      }
    },
    [setState],
  );

  const ask = useCallback(
    async (question: string) => {
      if (live.current.turns.some((t) => t.status === "running")) return;
      const id = uid();
      const started = Date.now();
      const { session, history } = live.current;
      setState((s) => ({ ...s, turns: [...s.turns, { id, question, started, status: "running", phase: "Thinking…", steps: [], runIds: [], answer: "" }] }));
      try {
        const accepted = await post<{ status_url: string; events_url: string }>(
          "/api/invocations",
          { id: uid(), session_id: session, background: true, stream: true, input: { messages: [...history, { role: "user", content: question }] } },
          { "X-Routing-Key": session },
        );
        const urls = { status: accepted.status_url, events: accepted.events_url };
        setState((s) => editTurn(s, id, (x) => ({ ...x, urls })));
        await follow(id, started, question, urls, session);
      } catch (e) {
        setState((s) => editTurn(s, id, (x) => ({ ...x, status: "error", error: problem(e) })));
      }
    },
    [follow, setState],
  );

  // A reload during a run picks the run up again: the invocation kept going on the server.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;
    for (const turn of live.current.turns) {
      if (turn.status !== "running") continue;
      if (!turn.urls) {
        setState((s) => editTurn(s, turn.id, (x) => ({ ...x, status: "error", error: "Interrupted by a reload before the copilot started." })));
        continue;
      }
      setState((s) => editTurn(s, turn.id, (x) => ({ ...x, steps: [], runIds: [], answer: "" })));
      follow(turn.id, turn.started, turn.question, turn.urls, live.current.session);
    }
  }, [follow, setState]);

  const handled = useRef<number | null>(null);
  useEffect(() => {
    if (incoming?.page === "copilot" && handled.current !== incoming.nonce) {
      handled.current = incoming.nonce;
      ask(incoming.question);
    }
  }, [incoming, ask]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={Sparkles}
        title="Ops Copilot"
        subtitle="Works payment incidents with the approved runbooks, as you"
        badges={
          <>
            <Badge kind="build">copilot and guardrails</Badge>
            <Badge kind="preview">Agent Bricks runtime</Badge>
          </>
        }
        actions={
          <Button icon={Plus} disabled={busy} onClick={() => setState(fresh())}>
            New conversation
          </Button>
        }
      />
      <div ref={scroller} className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto flex max-w-4xl flex-col gap-5">
          {state.turns.length === 0 ? (
            <Welcome
              icon={Sparkles}
              title="Work the incident with the copilot"
              text="It asks Genie for the numbers and the knowledge base for the policy, cites every fact, and runs a runbook one approved step at a time, stopping for a human before any refund above SGD 500. Every tool runs with your own permissions."
              suggestions={SUGGESTIONS}
              onAsk={ask}
            />
          ) : (
            state.turns.map((turn) => <TurnView key={turn.id} turn={turn} runs={state.runs} />)
          )}
        </div>
      </div>
      <Composer placeholder="Ask the copilot about an incident, a runbook or a refund" busy={busy} onSend={ask} />
    </div>
  );
}
