import clsx from "clsx";
import { BookOpen, ChevronDown, Lock, SearchX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, problem, readSSE } from "../api";
import { ChatActions, ChatHistoryPanel } from "../components/ChatHistory";
import { Composer } from "../components/Composer";
import { Citation, Markdown } from "../components/Markdown";
import { Badge, BotCard, ErrorNote, PageHeader, Pill, Spinner, type Suggestion, Tier, UserBubble, Welcome } from "../components/ui";
import { useChatHistory } from "../history";
import type { Incoming } from "../types";
import { count, uid, useSessionState } from "../util";

// The knowledge chatbot (T16's retrieval and grounded answer): only the tiers the visitor's groups entitle them
// to are searched, code abstains below the tuned reranker threshold, and every sentence of an answer cites the
// passage it came from. Each question is answered on its own.

interface Passage { label: string; doc_id: string; page: number; title: string; tier: string; version?: string | null; modified?: string; score: number; text: string }
interface Turn {
  id: string;
  question: string;
  status: "searching" | "answering" | "done" | "error";
  passages: Passage[];
  tiers: string[];
  refused: string[];
  threshold?: number;
  answer?: string;
  abstained?: boolean;
  abstainedBy?: string | null;
  citations: string[];
  usage?: { input: number; output: number; cache_read?: number | null } | null;
  model?: string;
  searchSeconds?: number;
  answerSeconds?: number;
  error?: string;
}
interface State { turns: Turn[] }

// Questions known to work: from the golden set (config/golden_qa.yaml), each asked through this page on 22 Oct. Finance
// questions need the finance tier; the last two must abstain, the second because the model knows an answer the
// documents don't give. They show as cards on an empty page, then as chips above the question box.
const SUGGESTIONS: Suggestion[] = [
  { kind: "Incident policy", label: "SEV2 acknowledgement", question: "How quickly must a SEV2 payment incident be acknowledged?" },
  { kind: "Policy beats an old note", label: "Refund approval limit", question: "What refund batch total requires approval before it is executed?" },
  { kind: "Refunds", label: "Refundable failure codes", question: "Which failure codes make a failed payment eligible for a refund?" },
  { kind: "Runbook and Slack", label: "Who to page for RB-014", question: "Before starting RB-014, which PagerDuty schedule do you page?" },
  { kind: "Finance tier", label: "acq_7 SLA credit", tier: "finance", question: "What service credit can Meridian claim when acq_7 breaches its SLA?" },
  { kind: "Finance tier", label: "acq_3 card fee", tier: "finance", question: "What is the merchant discount rate for card payments through acq_3?" },
  { kind: "Out of scope: it abstains", label: "Out of scope", question: "What will the SGD to USD exchange rate be next month?" },
  { kind: "Not in the documents: it abstains", label: "Not in the documents", question: "What is Singapore's current GST rate?" },
];

const fresh = (): State => ({ turns: [] });

// A saved chat whose answer was still streaming when it was left: the page that read the stream is gone.
const settle = (s: State): State => ({ turns: s.turns.map((t) => (t.status === "searching" || t.status === "answering" ? { ...t, status: "error", error: "This answer was still coming when the chat was left. Ask again." } : t)) });

const editTurn = (s: State, id: string, fn: (t: Turn) => Turn): State => ({ turns: s.turns.map((t) => (t.id === id ? fn(t) : t)) });

function PassageCard({ p, id, cited, threshold, below }: { p: Passage; id: string; cited: boolean; threshold?: number; below: boolean }) {
  const [open, setOpen] = useState(false);
  const share = Math.max(0.04, Math.min(1, p.score));
  return (
    <div id={id} className={clsx("rounded-2xl border bg-white p-3.5 transition", cited ? "border-navy-700/40 shadow-sm" : "border-line", below && "opacity-70")}>
      <div className="flex flex-wrap items-center gap-2">
        <Citation label={p.label} />
        <span className="text-[13.5px] font-semibold">{p.title}</span>
        <Tier name={p.tier} />
        {cited ? <Pill tone="ok">cited</Pill> : null}
        <span className="ml-auto text-[11.5px] text-muted">
          {p.version ? `version ${p.version} · ` : ""}
          {p.modified ? `changed ${p.modified}` : ""}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2 text-[11.5px] text-muted" title="Reranker relevance; the chatbot abstains when the best passage is below the threshold">
        <span className="w-16">relevance</span>
        <div className="relative h-1.5 flex-1 rounded-full bg-black/5">
          <div className={clsx("h-1.5 rounded-full", below ? "bg-[#CBD5D9]" : "bg-info")} style={{ width: `${share * 100}%` }} />
          {threshold !== undefined ? <div className="absolute -top-1 h-3.5 w-0.5 bg-warn" style={{ left: `${Math.min(1, threshold) * 100}%` }} /> : null}
        </div>
        <span className="w-10 text-right tabular-nums">{p.score.toFixed(2)}</span>
      </div>
      <p className={clsx("mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink/85", !open && "line-clamp-3")}>{p.text}</p>
      <button type="button" onClick={() => setOpen(!open)} className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-info">
        <ChevronDown className={clsx("size-3.5 transition", open && "rotate-180")} />
        {open ? "Show less" : "Show the passage"}
      </button>
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  const focus = (label: string) => {
    const el = document.getElementById(`p-${turn.id}-${label}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  };
  const byScore = turn.abstainedBy === "score threshold";
  const ordered = [...turn.passages].sort((a, b) => Number(turn.citations.includes(b.label)) - Number(turn.citations.includes(a.label)));
  return (
    <>
      <UserBubble text={turn.question} />
      <BotCard icon={BookOpen} tone="violet">
        {turn.status === "searching" ? (
          <div className="flex items-center gap-2 text-[13.5px] text-muted">
            <Spinner />
            Searching the knowledge base you can read…
          </div>
        ) : null}
        {turn.status === "answering" ? (
          <div className="mb-3 flex items-center gap-2 text-[13.5px] text-muted">
            <Spinner />
            Writing a cited answer from {turn.passages.length} passage{turn.passages.length === 1 ? "" : "s"}…
          </div>
        ) : null}
        {turn.status === "error" ? <ErrorNote>{turn.error}</ErrorNote> : null}
        {turn.status === "done" && turn.answer ? (
          turn.abstained ? (
            <div className="flex items-start gap-3 rounded-xl bg-paper px-4 py-3">
              <SearchX className="mt-0.5 size-5 text-muted" />
              <div>
                <p className="text-[14.5px] font-medium">Not in the knowledge base</p>
                <p className="text-[13px] text-muted">
                  {byScore
                    ? "No passage you can read was relevant enough, so it did not answer rather than guess."
                    : "The passages it found did not contain the answer, so it said so rather than guess."}
                </p>
              </div>
            </div>
          ) : (
            <Markdown text={turn.answer} onCite={focus} />
          )
        ) : null}
        {turn.tiers.length || turn.status === "done" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
            <span>Searched</span>
            {turn.tiers.map((t) => (
              <Tier key={t} name={t} />
            ))}
            {turn.refused.length ? (
              <span className="inline-flex items-center gap-1 text-bad">
                <Lock className="size-3.5" /> refused: {turn.refused.join(", ")}
              </span>
            ) : null}
            {turn.searchSeconds !== undefined ? <span>· {turn.searchSeconds} s</span> : null}
            {turn.answerSeconds !== undefined && !(turn.abstained && byScore) ? (
              <span>
                · answered by {turn.model} in {turn.answerSeconds} s
                {turn.usage ? ` · ${count(turn.usage.input)} tokens in, ${count(turn.usage.output)} out` : ""}
              </span>
            ) : null}
          </div>
        ) : null}
        {ordered.length ? (
          <div className="mt-4 border-t border-line pt-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
              {byScore ? `Closest passages, all below the relevance threshold (${turn.threshold?.toFixed(2)})` : "Retrieved passages"}
            </p>
            <div className="grid gap-2.5">
              {ordered.map((p) => (
                <PassageCard key={p.label} p={p} id={`p-${turn.id}-${p.label}`} cited={turn.citations.includes(p.label)} threshold={turn.threshold} below={byScore} />
              ))}
            </div>
          </div>
        ) : null}
      </BotCard>
    </>
  );
}

export default function KnowledgePage({ incoming, owner }: { incoming: Incoming | null; owner: string | null }) {
  const [state, setState] = useSessionState<State>("meridian.knowledge", fresh);
  const history = useChatHistory("knowledge", owner, state, setState, fresh, settle);
  const [showHistory, setShowHistory] = useState(false);
  const live = useRef(state);
  live.current = state;
  const scroller = useRef<HTMLDivElement>(null);
  const busy = state.turns.some((t) => t.status === "searching" || t.status === "answering");

  useEffect(() => {
    // The answer arrives after the passages; a turn interrupted by a reload cannot resume.
    setState((s) => ({ turns: s.turns.map((t) => (t.status === "searching" || t.status === "answering" ? { ...t, status: "error", error: "Interrupted by a reload. Ask again." } : t)) }));
  }, [setState]);

  useEffect(() => {
    if (state.turns.length) scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); // an empty page stays at its top
  }, [state.turns.length]);

  const ask = useCallback(
    async (question: string) => {
      if (live.current.turns.some((t) => t.status === "searching" || t.status === "answering")) return;
      const id = uid();
      setState((s) => ({ turns: [...s.turns, { id, question, status: "searching", passages: [], tiers: [], refused: [], citations: [] }] }));
      try {
        const resp = await fetch("/api/knowledge/ask", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
        if (!resp.ok) throw new ApiError(resp.status, (await resp.text()) || resp.statusText);
        let ended = false;
        await readSSE(resp, (name, d) => {
          if (name === "passages") {
            setState((s) => editTurn(s, id, (t) => ({ ...t, status: "answering", passages: d.passages, tiers: d.tiers, refused: d.refused, threshold: d.threshold, searchSeconds: d.seconds })));
          } else if (name === "answer") {
            ended = true;
            setState((s) => editTurn(s, id, (t) => ({ ...t, status: "done", answer: d.answer, abstained: d.abstained, abstainedBy: d.abstained_by, citations: d.citations, usage: d.usage, model: d.model, answerSeconds: d.seconds })));
          } else if (name === "error") {
            ended = true;
            setState((s) => editTurn(s, id, (t) => ({ ...t, status: "error", error: d.message })));
          }
        });
        if (!ended) throw new Error("The answer did not arrive. Ask again.");
      } catch (e) {
        setState((s) => editTurn(s, id, (t) => ({ ...t, status: "error", error: problem(e) })));
      }
    },
    [setState],
  );

  const handled = useRef<number | null>(null);
  useEffect(() => {
    if (incoming?.page === "knowledge" && handled.current !== incoming.nonce) {
      handled.current = incoming.nonce;
      ask(incoming.question);
    }
  }, [incoming, ask]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={BookOpen}
        title="Knowledge"
        subtitle="Ask policies, runbooks, fee schedules, SLAs and #ops-incidents"
        badges={
          <>
            <Badge kind="native">AI Search</Badge>
            <Badge kind="build">tier routing and cited answers</Badge>
          </>
        }
        actions={<ChatActions history={history} busy={busy} empty={!state.turns.length} onShow={() => setShowHistory(true)} />}
      />
      <div ref={scroller} className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto flex max-w-4xl flex-col gap-5">
          {state.turns.length === 0 ? (
            <Welcome
              icon={BookOpen}
              title="Ask the knowledge base"
              text="It searches only the tiers your groups give you, one AI Search index per tier, with hybrid search and a reranker. It answers only from the passages it found, cites each one, and says so when the answer is not there."
              suggestions={SUGGESTIONS}
              onAsk={ask}
            />
          ) : (
            state.turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
          )}
        </div>
      </div>
      <Composer placeholder="Ask about a policy, a runbook, a fee or an SLA" busy={busy} onSend={ask} examples={state.turns.length ? SUGGESTIONS : undefined} hint="Each question is answered on its own, from the passages shown under the answer" />
      <ChatHistoryPanel history={history} open={showHistory} onClose={() => setShowHistory(false)} busy={busy} label="Knowledge" />
    </div>
  );
}
