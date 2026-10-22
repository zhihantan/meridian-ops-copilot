import clsx from "clsx";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Info, Network, Pause, Play, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, problem } from "../api";
import { EDGE_KINDS, FLOWS, INTRO, KINDS, NODES, type Kind } from "../architecture";
import { Architecture, EDGE_COLOR, EDGE_DASH, KindTag } from "../components/Architecture";
import { Button, ErrorNote, PageHeader } from "../components/ui";
import type { AboutInfo, Page } from "../types";
import { useSessionState } from "../util";

const STEP_MS = 4500; // time on each step of a walkthrough

const sgt = (iso: string) =>
  `${new Date(iso).toLocaleString("en-SG", { timeZone: "Asia/Singapore", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} SGT`;

/** The architecture of the whole POC: every box opens its asset in the workspace, and each demo scene is a path. */
export default function AboutPage({ active, navigate }: { active: boolean; navigate: (p: Page) => void }) {
  const [info, setInfo] = useState<AboutInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind | null>(null);
  const [flowId, setFlowId] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [introOpen, setIntroOpen] = useSessionState("meridian.about.intro", () => true);

  useEffect(() => {
    api<AboutInfo>("/api/about")
      .then(setInfo)
      .catch((e) => setError(problem(e)));
  }, []);

  const flow = FLOWS.find((f) => f.id === flowId) ?? null;
  const last = flow ? flow.steps.length - 1 : 0;
  const counts = useMemo(() => Object.fromEntries(KINDS.map((k) => [k.kind, NODES.filter((n) => n.kinds.includes(k.kind)).length])), []);

  const start = (id: string) => {
    setFlowId(id);
    setStep(0);
    setKind(null);
    setPlaying(true);
  };
  const stop = useCallback(() => {
    setFlowId(null);
    setPlaying(false);
  }, []);
  const go = useCallback(
    (i: number) => {
      setPlaying(false);
      setStep(Math.max(0, Math.min(last, i)));
    },
    [last],
  );

  // Play moves to the next step on a timer, and stops at the last one or when the page is left.
  useEffect(() => {
    if (!playing || !flow || !active) return;
    if (step >= last) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => setStep((s) => s + 1), STEP_MS);
    return () => clearTimeout(timer);
  }, [playing, flow, step, last, active]);

  useEffect(() => {
    if (!active || !flow) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(step + 1);
      else if (e.key === "ArrowLeft") go(step - 1);
      else if (e.key === "Escape") stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, flow, step, go, stop]);

  const filter = (
    <div className="flex items-center gap-1 rounded-xl border border-line bg-white p-1 shadow-sm" role="group" aria-label="Highlight by label">
      <span className="px-1.5 text-[11.5px] font-medium text-muted">Highlight</span>
      {KINDS.map((k) => (
        <button
          key={k.kind}
          type="button"
          title={k.text}
          aria-pressed={kind === k.kind}
          onClick={() => {
            stop();
            setKind(kind === k.kind ? null : k.kind);
          }}
          className={clsx("inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] transition", kind === k.kind ? "bg-navy-900 text-white" : "text-ink hover:bg-paper")}
        >
          <KindTag kind={k.kind} />
          <span className="tabular-nums">{counts[k.kind]}</span>
        </button>
      ))}
    </div>
  );

  // What the POC is for, above the diagram. Hiding it, for this tab, brings the whole diagram onto one screen.
  const intro = introOpen ? (
    <section className="rise mb-3 rounded-2xl border border-line bg-white px-6 pb-4 pt-3.5 shadow-[0_1px_2px_rgba(27,49,57,0.05),0_6px_16px_rgba(27,49,57,0.04)]">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">About this proof of concept · synthetic data</p>
          <h2 className="mt-0.5 text-[17px] font-semibold leading-snug tracking-tight text-ink">{INTRO.title}</h2>
        </div>
        <Button variant="ghost" icon={ChevronUp} onClick={() => setIntroOpen(false)}>
          Hide
        </Button>
      </div>
      <div className="mt-2.5 grid grid-cols-[5fr_6fr] gap-8">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-brand-dark">The problem</p>
          <p className="mt-1 text-[13.5px] leading-[1.55] text-ink">{INTRO.problem}</p>
        </div>
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#067647]">What it does</p>
          <p className="mt-1 text-[13.5px] leading-[1.55] text-ink">{INTRO.solution}</p>
        </div>
      </div>
    </section>
  ) : (
    <button
      type="button"
      onClick={() => setIntroOpen(true)}
      className="mb-3 flex w-full items-center gap-2 rounded-xl border border-dashed border-line bg-white/60 px-4 py-2 text-left text-[13px] text-muted transition hover:border-navy-700/40 hover:text-ink"
    >
      <Info className="size-4 shrink-0" aria-hidden />
      <span className="font-medium text-ink">{INTRO.title}.</span>
      <span>The problem it solves, and what it does.</span>
      <ChevronDown className="ml-auto size-4 shrink-0" aria-hidden />
    </button>
  );

  return (
    <>
      <PageHeader icon={Network} title="About" subtitle="How the Meridian Ops Copilot is built. Hover a box for what it does; click to open it in the workspace." actions={filter} />

      {flow ? (
        <div className="rise border-b border-line bg-white px-8 py-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="rounded-full bg-brand px-2.5 py-0.5 text-[11.5px] font-bold text-white">Scene {flow.scene}</span>
            <span className="text-[14.5px] font-semibold">{flow.title}</span>
            <ol className="flex flex-wrap items-center gap-1" aria-label="Steps">
              {flow.steps.map((s, i) => (
                <li key={i}>
                  <button
                    type="button"
                    title={s.title}
                    aria-current={i === step ? "step" : undefined}
                    onClick={() => go(i)}
                    className={clsx(
                      "grid size-6 place-items-center rounded-full text-[11px] font-bold transition",
                      i === step ? "bg-brand text-white shadow" : i < step ? "bg-navy-900 text-white" : "bg-paper text-navy-900 ring-1 ring-line hover:ring-navy-700/40",
                    )}
                  >
                    {i + 1}
                  </button>
                </li>
              ))}
            </ol>
            <div className="ml-auto flex items-center gap-1.5">
              <Button icon={ChevronLeft} onClick={() => go(step - 1)} disabled={step === 0} aria-label="Previous step" />
              {step >= last && !playing ? (
                <Button
                  variant="primary"
                  icon={RotateCcw}
                  onClick={() => {
                    setStep(0);
                    setPlaying(true);
                  }}
                >
                  Replay
                </Button>
              ) : (
                <Button variant="primary" icon={playing ? Pause : Play} onClick={() => setPlaying(!playing)}>
                  {playing ? "Pause" : "Play"}
                </Button>
              )}
              <Button icon={ChevronRight} onClick={() => go(step + 1)} disabled={step >= last} aria-label="Next step" />
              <Button variant="ghost" icon={X} onClick={stop}>
                Close
              </Button>
            </div>
          </div>
          <p className="mt-2 text-[13.5px] leading-snug text-ink" aria-live="polite">
            <span className="font-semibold">
              {step + 1}. {flow.steps[step].title}.
            </span>{" "}
            {flow.steps[step].text}
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line bg-white/60 px-8 py-2">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Scenes</span>
          {FLOWS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => start(f.id)}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white py-[3px] pl-[3px] pr-2.5 text-[12px] font-medium text-ink shadow-sm transition hover:-translate-y-px hover:border-navy-700/40 hover:shadow"
            >
              <span className="grid size-5 place-items-center rounded-full bg-navy-900 text-[10.5px] font-bold text-white">{f.scene}</span>
              {f.title}
            </button>
          ))}
        </div>
      )}

      <div className="scrollbar-thin min-h-0 flex-1 overflow-auto px-6 py-4">
        {error ? (
          <div className="mx-auto mb-3 max-w-3xl">
            <ErrorNote>The workspace links could not be loaded ({error}). The diagram still shows how the parts connect.</ErrorNote>
          </div>
        ) : null}
        <Architecture info={info} active={active} kind={kind} flow={flow} step={step} onStep={go} navigate={navigate} intro={intro}>
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-[11.5px] text-muted">
            {EDGE_KINDS.map((k) => (
              <span key={k.kind} className="inline-flex items-center gap-1.5">
                <svg width="26" height="8" aria-hidden>
                  <line x1="0" y1="4" x2="26" y2="4" stroke={EDGE_COLOR[k.kind]} strokeWidth="2" strokeDasharray={EDGE_DASH[k.kind]} />
                </svg>
                {k.label}
              </span>
            ))}
            <span className="ml-auto">More connections appear when you hover a box.</span>
          </div>
          <p className="mt-2 px-1 text-[11.5px] leading-relaxed text-muted">
            Links open in a new tab, where the workspace checks your own permissions. The jobs, the pipeline and the dashboard are linked from the bundle's own deployment
            summary{info?.links_generated_at ? `, read ${sgt(info.links_generated_at)}` : ""}; boxes without a link have no page of their own. All data is synthetic.
          </p>
        </Architecture>
      </div>
    </>
  );
}
