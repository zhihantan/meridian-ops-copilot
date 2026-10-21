import clsx from "clsx";
import { Check, Database, ExternalLink, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, post, problem, sleep } from "../api";
import { Composer } from "../components/Composer";
import { type GenieQuery, QueryResult } from "../components/GenieResult";
import { Markdown } from "../components/Markdown";
import { Badge, BotCard, Button, ErrorNote, PageHeader, Spinner, type Suggestion, UserBubble, Welcome } from "../components/ui";
import type { Incoming } from "../types";
import { uid, useNow, useSessionState } from "../util";

// Genie (NATIVE) answers from the governed gold tables; this page asks it directly, as the visitor. Questions in
// one conversation build on each other, so follow-ups can say "and for acq_3?".

interface GenieMessage { status: string; done: boolean; text: string | null; queries: GenieQuery[]; suggestions: string[]; error: string | null }
interface Turn {
  id: string;
  question: string;
  started: number;
  status: string;
  done: boolean;
  text?: string | null;
  queries: GenieQuery[];
  suggestions: string[];
  error?: string | null;
  conversationId?: string;
  messageId?: string;
  seconds?: number;
}
interface State { conversationId?: string; turns: Turn[] }

const SUGGESTIONS: Suggestion[] = [
  { kind: "Status", question: "Which acquirers are degraded right now?" },
  { kind: "Trend", question: "Daily failure rate for acq_7 over the last 14 days" },
  { kind: "Refunds", question: "What is the refundable failed amount for acq_7 in the last 24 hours?" },
  { kind: "Hourly detail", question: "Hourly payments and failures for acq_7 in the last 24 hours" },
];

const PHASES: { label: string; statuses: string[] }[] = [
  { label: "Reading the question", statuses: ["SUBMITTED", "FILTERING_CONTEXT", "FETCHING_METADATA"] },
  { label: "Writing the SQL", statuses: ["ASKING_AI"] },
  { label: "Running the query", statuses: ["PENDING_WAREHOUSE", "EXECUTING_QUERY"] },
  { label: "Answer", statuses: ["COMPLETED"] },
];

const editTurn = (s: State, id: string, fn: (t: Turn) => Turn): State => ({ ...s, turns: s.turns.map((t) => (t.id === id ? fn(t) : t)) });

function Progress({ status, since }: { status: string; since: number }) {
  const now = useNow(true);
  const at = Math.max(0, PHASES.findIndex((p) => p.statuses.includes(status)));
  return (
    <div className="flex flex-wrap items-center gap-2 text-[13px]">
      {PHASES.slice(0, 3).map((p, i) => (
        <span key={p.label} className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1", i < at ? "bg-ok-soft text-[#067647]" : i === at ? "bg-info-soft text-info" : "bg-black/5 text-muted")}>
          {i < at ? <Check className="size-3.5" strokeWidth={3} /> : i === at ? <Spinner className="size-3.5 text-info" /> : null}
          {p.label}
        </span>
      ))}
      <span className="ml-auto tabular-nums text-muted">{Math.floor((now - since) / 1000)} s</span>
    </div>
  );
}

function TurnView({ turn, onAsk, busy }: { turn: Turn; onAsk: (q: string) => void; busy: boolean }) {
  return (
    <>
      <UserBubble text={turn.question} />
      <BotCard icon={Database} tone="info">
        {!turn.done && !turn.error ? <Progress status={turn.status} since={turn.started} /> : null}
        {turn.error ? <ErrorNote>{turn.error}</ErrorNote> : null}
        {turn.done && !turn.error ? (
          <>
            {turn.text ? <Markdown text={turn.text} /> : null}
            {turn.queries.map((q) => (
              <QueryResult key={q.label} q={q} />
            ))}
            {!turn.text && !turn.queries.length ? <p className="text-[14px] text-muted">Genie returned no answer for this question.</p> : null}
            {turn.suggestions.length ? (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Ask next</span>
                {turn.suggestions.map((s) => (
                  <button key={s} type="button" disabled={busy} onClick={() => onAsk(s)} className="rounded-full border border-line bg-white px-3 py-1 text-[12.5px] hover:border-navy-700/40 disabled:opacity-50">
                    {s}
                  </button>
                ))}
              </div>
            ) : null}
            <p className="mt-3 text-[12.5px] text-muted">
              {turn.seconds} s · Genie ran the SQL with your permissions
            </p>
          </>
        ) : null}
      </BotCard>
    </>
  );
}

export default function GeniePage({ incoming }: { incoming: Incoming | null }) {
  const [state, setState] = useSessionState<State>("meridian.genie", () => ({ turns: [] }));
  const live = useRef(state);
  live.current = state;
  const [space, setSpace] = useState<{ title: string; url: string; description?: string } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const busy = state.turns.some((t) => !t.done && !t.error);

  useEffect(() => {
    api<{ title: string; url: string; description?: string }>("/api/genie/space").then(setSpace).catch(() => setSpace(null));
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [state.turns]);

  const poll = useCallback(
    async (id: string, started: number, conversationId: string, messageId: string) => {
      const deadline = Date.now() + 4 * 60_000;
      try {
        for (;;) {
          const m = await api<GenieMessage>(`/api/genie/${encodeURIComponent(conversationId)}/${encodeURIComponent(messageId)}`);
          const seconds = Math.round((Date.now() - started) / 1000);
          setState((s) => editTurn(s, id, (t) => ({ ...t, status: m.status, done: m.done, text: m.text, queries: m.queries, suggestions: m.suggestions, error: m.done && m.status !== "COMPLETED" ? m.error || `Genie stopped: ${m.status.toLowerCase()}` : null, seconds })));
          if (m.done) return;
          if (Date.now() > deadline) throw new Error("Genie did not answer within 4 minutes.");
          await sleep(1500);
        }
      } catch (e) {
        setState((s) => editTurn(s, id, (t) => ({ ...t, error: problem(e) })));
      }
    },
    [setState],
  );

  const ask = useCallback(
    async (question: string) => {
      if (live.current.turns.some((t) => !t.done && !t.error)) return;
      const id = uid();
      const started = Date.now();
      setState((s) => ({ ...s, turns: [...s.turns, { id, question, started, status: "SUBMITTED", done: false, queries: [], suggestions: [] }] }));
      try {
        const r = await post<{ conversation_id: string; message_id: string }>("/api/genie/ask", { question, conversation_id: live.current.conversationId ?? null });
        setState((s) => editTurn({ ...s, conversationId: r.conversation_id }, id, (t) => ({ ...t, conversationId: r.conversation_id, messageId: r.message_id })));
        await poll(id, started, r.conversation_id, r.message_id);
      } catch (e) {
        setState((s) => editTurn(s, id, (t) => ({ ...t, error: problem(e) })));
      }
    },
    [poll, setState],
  );

  // A reload while Genie is still working resumes polling the same message.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;
    for (const t of live.current.turns) {
      if (t.done || t.error) continue;
      if (t.conversationId && t.messageId) poll(t.id, t.started, t.conversationId, t.messageId);
      else setState((s) => editTurn(s, t.id, (x) => ({ ...x, error: "Interrupted by a reload before Genie started." })));
    }
  }, [poll, setState]);

  const handled = useRef<number | null>(null);
  useEffect(() => {
    if (incoming?.page === "genie" && handled.current !== incoming.nonce) {
      handled.current = incoming.nonce;
      ask(incoming.question);
    }
  }, [incoming, ask]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={Database}
        title="Genie"
        subtitle={space ? `Ask the payments data · ${space.title}` : "Ask the payments data in plain English"}
        badges={
          <>
            <Badge kind="native">Genie</Badge>
            <Badge kind="build">this view</Badge>
          </>
        }
        actions={
          <>
            {space?.url ? (
              <Button icon={ExternalLink} onClick={() => window.open(space.url, "_blank", "noopener")}>
                Open in Genie
              </Button>
            ) : null}
            <Button icon={Plus} disabled={busy} onClick={() => setState({ turns: [] })}>
              New conversation
            </Button>
          </>
        }
      />
      <div ref={scroller} className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-5">
          {state.turns.length === 0 ? (
            <Welcome
              icon={Database}
              title="Ask the payments data"
              text="Genie writes SQL over the governed gold tables (payments, failures, refundable amounts and acquirer status) and runs it with your own grants, masks and row filters. You see its SQL, the rows, and a chart when the rows chart. Follow-ups build on the conversation."
              suggestions={SUGGESTIONS}
              onAsk={ask}
            />
          ) : (
            state.turns.map((turn) => <TurnView key={turn.id} turn={turn} onAsk={ask} busy={busy} />)
          )}
        </div>
      </div>
      <Composer placeholder="Ask Genie about payments, failures or refundable amounts" busy={busy} onSend={ask} hint="Genie remembers this conversation: follow-ups can build on earlier answers" />
    </div>
  );
}
