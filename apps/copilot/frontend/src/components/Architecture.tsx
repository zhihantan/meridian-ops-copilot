import clsx from "clsx";
import { ArrowUpRight } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";

import { EDGES, LANES, NODES, type ArchEdge, type ArchNode, type EdgeKind, type Flow, type Kind, type LaneId } from "../architecture";
import type { AboutInfo, Page } from "../types";

// The diagram is laid out once at a fixed width, measured, and scaled to fit, so the lines always meet their boxes.
export const CANVAS_W = 1150;
const COLUMNS = "170px 192px 196px 366px 186px"; // sources, ingest, lakehouse, AI (two columns), experiences
const MIN_SCALE = 0.72;
const MAX_SCALE = 1.2;
const TIP_W = 300;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Link {
  href: string;
  external: boolean;
  page?: Page;
}

const split = (ref: string): [string, string] => {
  const i = ref.indexOf(":");
  return i < 0 ? [ref, ""] : [ref.slice(0, i), ref.slice(i + 1)];
};

/** Where a ref leads: a workspace URL built from /api/about, the repository on GitHub, or a page of this console. */
export function resolve(ref: string | undefined, info: AboutInfo | null): Link | null {
  if (!ref) return null;
  const [kind, rest] = split(ref);
  if (kind === "page") return { href: `#/${rest}`, external: false, page: rest as Page };
  if (!info) return null;
  if (kind === "github") return info.github ? { href: rest ? `${info.github}/blob/main/${rest}` : info.github, external: true } : null;
  if (!info.host) return null;
  const [schema, name] = rest.split(".");
  const uc = (...parts: string[]) => `${info.host}/explore/data/${parts.map(encodeURIComponent).join("/")}`;
  switch (kind) {
    case "catalog":
      return { href: uc(info.catalog), external: true };
    case "schema":
      return { href: uc(info.catalog, rest), external: true };
    case "table":
      return { href: uc(info.catalog, schema, name), external: true };
    case "volume":
      return { href: uc("volumes", info.catalog, schema, name), external: true };
    case "fn":
      return { href: uc("functions", info.catalog, schema, name), external: true };
    default: {
      const path = info.paths[ref];
      return path ? { href: info.host + path, external: true } : null;
    }
  }
}

/** What a click opens, in words, for the box's tooltip. */
function opens(ref: string | undefined, info: AboutInfo | null): string {
  if (!ref) return "No page of its own in the workspace.";
  const [kind, rest] = split(ref);
  const c = info?.catalog ?? "meridian";
  const what: Record<string, string> = {
    job: `the job in Lakeflow Jobs${rest.startsWith("staging/") ? " (staging)" : ""}`,
    pipeline: "the pipeline and its updates",
    dashboard: "the published dashboard",
    folder: "the files prod was deployed from",
    genie: "the Genie space",
    app: "the app: deployments, logs and authorization",
    experiment: "the MLflow experiment with the traces",
    search: "the AI Search endpoint and its indexes",
    endpoint: "the serving endpoint",
    catalog: `catalog ${c} in Catalog Explorer, with its policies`,
    schema: `schema ${c}.${rest} in Catalog Explorer`,
    table: `${c}.${rest} in Catalog Explorer`,
    volume: `volume ${c}.${rest} in Catalog Explorer`,
    fn: `${c}.${rest} in Catalog Explorer`,
    github: rest ? `${rest} on GitHub` : "the repository on GitHub",
    page: "that page of this console",
  };
  return `Opens ${what[kind] ?? ref}.`;
}

/** Fill {name|fallback} from the names /api/about returns. */
export const fill = (text: string, names: Record<string, string> | undefined) =>
  text.replace(/\{(\w+)\|([^}]*)\}/g, (_, key: string, fallback: string) => names?.[key] ?? fallback);

const KIND_TAG: Record<Kind, string> = {
  native: "bg-ok text-white",
  preview: "bg-warn text-navy-900",
  build: "bg-[#5a6f77] text-white",
  external: "border border-navy-700/35 text-navy-800 bg-white",
};

export const KIND_RING: Record<Kind, string> = {
  native: "ring-ok",
  preview: "ring-warn",
  build: "ring-[#5a6f77]",
  external: "ring-navy-700",
};

export function KindTag({ kind, className }: { kind: Kind; className?: string }) {
  return <span className={clsx("inline-flex items-center rounded px-1 py-px text-[9.5px] font-semibold leading-[13px] tracking-wide", KIND_TAG[kind], className)}>{kind.toUpperCase()}</span>;
}

export const EDGE_COLOR: Record<EdgeKind, string> = {
  data: "#2c505c",
  trigger: "#b7791f",
  ai: "#6b4fbb",
  control: "#e02b17",
  governs: "#00a972",
  deliver: "#5f737b",
};

export const EDGE_DASH: Partial<Record<EdgeKind, string>> = { trigger: "5 4", deliver: "5 4", governs: "2 3" };

const LANE_TILE: Record<LaneId, string> = {
  sources: "bg-navy-100 text-navy-900",
  ingest: "bg-info-soft text-info",
  lakehouse: "bg-ok-soft text-[#067647]",
  ai: "bg-violet-soft text-violet",
  experience: "bg-brand-soft text-brand-dark",
  govern: "bg-warn-soft text-[#8A5A00]",
  deliver: "bg-black/5 text-muted",
};

/** A curve between two boxes: side to side across lanes, end to end within a column, around the side past others. */
function curve(a: Rect, b: Rect) {
  let p0, p1, p2, p3;
  if (b.x >= a.x + a.w - 2 || b.x + b.w <= a.x + 2) {
    const right = b.x >= a.x + a.w - 2;
    const sx = right ? a.x + a.w : a.x;
    const tx = right ? b.x : b.x + b.w;
    const sy = a.y + a.h / 2;
    const ty = b.y + b.h / 2;
    const dx = Math.max(22, Math.abs(tx - sx) / 2) * (right ? 1 : -1);
    [p0, p1, p2, p3] = [[sx, sy], [sx + dx, sy], [tx - dx, ty], [tx, ty]];
  } else if (Math.abs(a.x - b.x) < 4 && Math.abs(b.y - (a.y + a.h)) > 30 && Math.abs(a.y - (b.y + b.h)) > 30) {
    const sx = a.x;
    const sy = a.y + a.h / 2;
    const ty = b.y + b.h / 2;
    [p0, p1, p2, p3] = [[sx, sy], [sx - 34, sy], [sx - 34, ty], [sx, ty]];
  } else {
    const down = b.y >= a.y + a.h / 2;
    const sx = a.x + a.w / 2;
    const tx = b.x + b.w / 2;
    const sy = down ? a.y + a.h : a.y;
    const ty = down ? b.y : b.y + b.h;
    const dy = Math.max(10, Math.abs(ty - sy) / 2) * (down ? 1 : -1);
    [p0, p1, p2, p3] = [[sx, sy], [sx, sy + dy], [tx, ty - dy], [tx, ty]];
  }
  const mid = [(p0[0] + 3 * p1[0] + 3 * p2[0] + p3[0]) / 8, (p0[1] + 3 * p1[1] + 3 * p2[1] + p3[1]) / 8];
  return { d: `M${p0[0]},${p0[1]} C${p1[0]},${p1[1]} ${p2[0]},${p2[1]} ${p3[0]},${p3[1]}`, mid };
}

const NEIGHBORS = (() => {
  const map = new Map<string, Set<string>>();
  for (const e of EDGES) {
    if (!map.has(e.from)) map.set(e.from, new Set());
    if (!map.has(e.to)) map.set(e.to, new Set());
    map.get(e.from)!.add(e.to);
    map.get(e.to)!.add(e.from);
  }
  return map;
})();

const BY_ID = new Map(NODES.map((n) => [n.id, n]));

interface Props {
  info: AboutInfo | null;
  active: boolean;
  kind: Kind | null;
  flow: Flow | null;
  step: number;
  onStep: (i: number) => void;
  navigate: (p: Page) => void;
  children?: ReactNode; // shown under the diagram, at its width
}

export function Architecture({ info, active, kind, flow, step, onStep, navigate, children }: Props) {
  const outer = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<string, HTMLDivElement>());
  const [rects, setRects] = useState<Record<string, Rect>>({});
  const [height, setHeight] = useState(0);
  const [scale, setScale] = useState(1);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tipH, setTipH] = useState(0);
  const leave = useRef<number | undefined>(undefined);

  const measure = useCallback(() => {
    const c = canvas.current;
    if (!c || !c.offsetWidth) return; // hidden: the page measures again when it is shown
    const next: Record<string, Rect> = {};
    boxes.current.forEach((el, id) => (next[id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }));
    setRects(next);
    setHeight(c.offsetHeight);
  }, []);

  useLayoutEffect(() => {
    if (active) measure();
  }, [active, info, measure]);

  useEffect(() => {
    document.fonts?.ready.then(measure);
    const c = canvas.current;
    const o = outer.current;
    if (!c || !o) return;
    const fit = () => o.clientWidth && setScale(Math.min(MAX_SCALE, Math.max(MIN_SCALE, o.clientWidth / CANVAS_W)));
    const ro = new ResizeObserver(() => {
      fit();
      measure();
    });
    ro.observe(c);
    ro.observe(o);
    return () => ro.disconnect();
  }, [measure]);

  // In a walkthrough, keep the current box in view.
  const current = flow?.steps[step]?.node;
  useEffect(() => {
    if (current && active) boxes.current.get(current)?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [current, active]);

  useLayoutEffect(() => {
    setTipH(tipRef.current?.offsetHeight ?? 0);
  }, [hovered]);

  const enter = (id: string) => {
    window.clearTimeout(leave.current);
    setHovered(id);
  };
  const exit = () => {
    window.clearTimeout(leave.current);
    leave.current = window.setTimeout(() => setHovered(null), 90);
  };

  // What is in focus: the hovered box and its neighbours, else the walkthrough's boxes, else one label.
  const focus = useMemo(() => {
    if (hovered) return new Set([hovered, ...(NEIGHBORS.get(hovered) ?? [])]);
    if (flow) return new Set(flow.steps.map((s) => s.node));
    if (kind) return new Set(NODES.filter((n) => n.kinds.includes(kind)).map((n) => n.id));
    return null;
  }, [hovered, flow, kind]);

  const stepsOf = useMemo(() => {
    const map = new Map<string, number[]>();
    flow?.steps.forEach((s, i) => map.set(s.node, [...(map.get(s.node) ?? []), i]));
    return map;
  }, [flow]);

  const edgeState = (e: ArchEdge): "hot" | "normal" | "dim" | "hidden" => {
    if (hovered) return e.from === hovered || e.to === hovered ? "hot" : e.quiet ? "hidden" : "dim";
    if (flow || kind) return e.quiet ? "hidden" : "dim";
    return e.quiet ? "hidden" : "normal";
  };

  const ready = Object.keys(rects).length === NODES.length;
  const edges = ready ? EDGES.map((e) => ({ e, state: edgeState(e), ...curve(rects[e.from], rects[e.to]) })).filter((x) => x.state !== "hidden") : [];
  const order = { dim: 0, normal: 1, hot: 2, hidden: -1 } as const;
  edges.sort((a, b) => order[a.state] - order[b.state]);

  // The walkthrough's path: done up to the current step, moving into it, faint after.
  const path =
    ready && flow
      ? flow.steps.slice(1).flatMap((s, i) => {
          const from = flow.steps[i].node;
          if (from === s.node) return [];
          return [{ key: `${i}`, ...curve(rects[from], rects[s.node]), phase: i + 1 < step ? "done" : i + 1 === step ? "now" : "next" }];
        })
      : [];

  const lane = (id: LaneId, column?: 0 | 1) => NODES.filter((n) => n.lane === id && (column === undefined || n.column === column));

  const box = (n: ArchNode) => {
    const link = resolve(n.ref, info);
    const dim = focus && !focus.has(n.id);
    const steps = stepsOf.get(n.id);
    const isCurrent = current === n.id;
    const open = (l: Link | null) => (e: MouseEvent) => {
      if (l?.page) {
        e.preventDefault();
        navigate(l.page);
      }
    };
    return (
      <div
        key={n.id}
        ref={(el) => {
          if (el) boxes.current.set(n.id, el);
          else boxes.current.delete(n.id);
        }}
        onMouseEnter={() => enter(n.id)}
        onMouseLeave={exit}
        className={clsx(
          "group relative z-[2] rounded-xl border bg-white px-2 py-1.5 shadow-[0_1px_2px_rgba(27,49,57,0.06)] transition duration-150",
          n.push && "mt-auto",
          hovered === n.id ? "-translate-y-px border-navy-700/45 shadow-[0_6px_18px_rgba(27,49,57,0.14)]" : "border-line",
          dim && "opacity-25 saturate-50",
          isCurrent && "ring-2 ring-brand ring-offset-2 ring-offset-paper",
          !hovered && !flow && kind && !dim && clsx("ring-2 ring-offset-1 ring-offset-paper", KIND_RING[kind]),
          link ? "cursor-pointer" : "cursor-default",
        )}
      >
        {link ? (
          <a
            href={link.href}
            target={link.external ? "_blank" : undefined}
            rel={link.external ? "noopener noreferrer" : undefined}
            onClick={open(link)}
            onFocus={() => enter(n.id)}
            onBlur={exit}
            aria-label={`${n.title}: ${opens(n.ref, info)}`}
            className="absolute inset-0 z-[1] rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
          />
        ) : null}
        <div className="flex items-start gap-1.5">
          <span className={clsx("mt-px grid size-5 shrink-0 place-items-center rounded-md", LANE_TILE[n.lane])}>
            <n.icon className="size-3" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] font-semibold leading-[15px] text-ink">{n.title}</p>
            <p className="truncate text-[10.5px] leading-[13px] text-muted">{fill(n.sub, info?.names)}</p>
          </div>
        </div>
        {link ? <ArrowUpRight className="absolute right-1 top-1 size-3 rounded-sm bg-white text-muted opacity-0 transition group-hover:opacity-100" aria-hidden /> : null}
        <div className="mt-1 flex flex-wrap items-center gap-[3px]">
          {n.kinds.map((k) => (
            <KindTag key={k} kind={k} />
          ))}
          {n.assets?.map((a) => {
            const l = resolve(a.ref, info);
            const label = fill(a.label, info?.names);
            const chip = "relative z-[2] max-w-full truncate rounded border px-1 text-[10px] leading-[14px]";
            return l ? (
              <a
                key={a.ref + a.label}
                href={l.href}
                target={l.external ? "_blank" : undefined}
                rel={l.external ? "noopener noreferrer" : undefined}
                onClick={open(l)}
                onFocus={() => enter(n.id)}
                onBlur={exit}
                title={opens(a.ref, info)}
                className={clsx(chip, "border-line bg-paper text-navy-800 hover:border-navy-700/50 hover:bg-white hover:text-ink")}
              >
                {label}
              </a>
            ) : (
              <span key={a.ref + a.label} className={clsx(chip, "border-dashed border-line text-muted")}>
                {label}
              </span>
            );
          })}
        </div>
        {steps ? (
          <span className="absolute -left-2 -top-2 z-[3] flex gap-0.5">
            {steps.map((i) => (
              <button
                key={i}
                type="button"
                onClick={() => onStep(i)}
                className={clsx("grid size-5 place-items-center rounded-full text-[10.5px] font-bold shadow", i === step ? "bg-brand text-white" : i < step ? "bg-navy-900 text-white" : "bg-white text-navy-900 ring-1 ring-navy-900/30")}
                aria-label={`Step ${i + 1}`}
              >
                {i + 1}
              </button>
            ))}
          </span>
        ) : null}
      </div>
    );
  };

  const header = (id: LaneId, extra?: ReactNode) => {
    const l = LANES.find((x) => x.id === id)!;
    return (
      <div className="mb-1.5 flex min-w-0 items-baseline gap-2 px-0.5" title={l.hint}>
        <p className="shrink-0 whitespace-nowrap text-[10.5px] font-bold uppercase tracking-[0.08em] text-navy-900">{l.title}</p>
        <p className="min-w-0 truncate text-[10.5px] text-muted">{l.hint}</p>
        {extra}
      </div>
    );
  };

  const tip = hovered && rects[hovered] ? BY_ID.get(hovered)! : null;
  let tipStyle: CSSProperties | undefined;
  if (tip) {
    const r = rects[tip.id];
    const left = r.x + r.w + 12 + TIP_W <= CANVAS_W ? r.x + r.w + 12 : Math.max(0, r.x - 12 - TIP_W);
    const top = Math.max(0, Math.min(r.y - 6, height - tipH - 4));
    tipStyle = { left, top, width: TIP_W };
  }

  return (
    <div ref={outer} className="w-full overflow-x-auto scrollbar-thin">
      <div className="mx-auto" style={{ width: CANVAS_W * scale }}>
      <div style={{ height: height ? height * scale : undefined }}>
        <div ref={canvas} className="relative" style={{ width: CANVAS_W, transform: `scale(${scale})`, transformOrigin: "0 0" }}>
          <div className="grid gap-2.5" style={{ gridTemplateColumns: COLUMNS }}>
            {(["sources", "ingest", "lakehouse", "ai", "experience"] as LaneId[]).map((id) => (
              <div key={id} className="flex flex-col rounded-2xl border border-line/80 bg-white/50 p-2">
                {header(id)}
                {id === "ai" ? (
                  <div className="grid flex-1 grid-cols-2 gap-2">
                    {([0, 1] as const).map((col) => (
                      <div key={col} className="flex flex-col gap-1.5">
                        <p className="-mt-0.5 px-0.5 text-[9.5px] font-semibold uppercase tracking-wider text-muted/80">{col === 0 ? "Platform services" : "The copilot"}</p>
                        {lane("ai", col).map(box)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-1 flex-col gap-1.5">{lane(id).map(box)}</div>
                )}
              </div>
            ))}
          </div>
          {(["govern", "deliver"] as LaneId[]).map((id) => (
            <div key={id} className="mt-2.5 rounded-2xl border border-line/80 bg-white/50 p-2">
              {header(id)}
              <div className="grid grid-cols-6 gap-2">{lane(id).map(box)}</div>
            </div>
          ))}

          <svg className="pointer-events-none absolute left-0 top-0 z-[1] overflow-visible" width={CANVAS_W} height={height || 1} aria-hidden>
            <defs>
              {Object.entries(EDGE_COLOR).map(([k, color]) => (
                <marker key={k} id={`arrow-${k}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0,0.5 L7.5,4 L0,7.5 z" fill={color} />
                </marker>
              ))}
              <marker id="arrow-flow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0.5 L7.5,4 L0,7.5 z" fill="#ff3621" />
              </marker>
            </defs>
            {edges.map(({ e, state, d }) => (
              <path
                key={`${e.from}-${e.to}`}
                d={d}
                fill="none"
                stroke={EDGE_COLOR[e.kind]}
                strokeWidth={state === "hot" ? 2.2 : 1.4}
                strokeDasharray={EDGE_DASH[e.kind]}
                strokeOpacity={state === "hot" ? 0.95 : state === "normal" ? 0.5 : 0.12}
                markerEnd={`url(#arrow-${e.kind})`}
                className="transition-[stroke-opacity] duration-150"
              />
            ))}
            {path.map((p) => (
              <path
                key={p.key}
                d={p.d}
                fill="none"
                stroke="#ff3621"
                strokeWidth={p.phase === "next" ? 1.6 : 2.6}
                strokeOpacity={p.phase === "next" ? 0.3 : 0.95}
                strokeDasharray={p.phase === "done" ? undefined : "6 6"}
                className={p.phase === "now" ? "flow-dash" : undefined}
                markerEnd="url(#arrow-flow)"
              />
            ))}
            {edges
              .filter((x) => x.state === "hot" && x.e.label)
              .map(({ e, mid }) => (
                <text key={`label-${e.from}-${e.to}`} x={mid[0]} y={mid[1] - 4} textAnchor="middle" className="fill-ink text-[10px] font-medium" stroke="#f7f5f2" strokeWidth={3} paintOrder="stroke">
                  {e.label}
                </text>
              ))}
          </svg>

          {tip && tipStyle ? (
            <div ref={tipRef} className="rise pointer-events-none absolute z-30 rounded-2xl border border-line bg-white p-4 shadow-[0_12px_32px_rgba(27,49,57,0.18)]" style={tipStyle}>
              <div className="flex items-start gap-2.5">
                <span className={clsx("grid size-8 shrink-0 place-items-center rounded-lg", LANE_TILE[tip.lane])}>
                  <tip.icon className="size-4" aria-hidden />
                </span>
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold leading-tight">{tip.title}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {tip.kinds.map((k) => (
                      <KindTag key={k} kind={k} />
                    ))}
                  </div>
                </div>
              </div>
              <p className="mt-2.5 text-[12.5px] leading-[1.5] text-ink">{tip.about}</p>
              <p className="mt-2.5 flex items-start gap-1 text-[11.5px] leading-snug text-navy-800">
                <ArrowUpRight className="mt-px size-3.5 shrink-0" aria-hidden />
                <span>{resolve(tip.ref, info) || !tip.ref ? opens(tip.ref, info) : "Its link isn't available in this deployment."}</span>
              </p>
              {tip.evidence ? <p className="mt-1 text-[11px] text-muted">Evidence: {tip.evidence}, in docs/evidence</p> : null}
            </div>
          ) : null}
        </div>
      </div>
      {children}
      </div>
    </div>
  );
}
