import clsx from "clsx";
import { ChartColumn, Check, Code, Copy, Table2 } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";

import { formatCell, isNumeric, isTime } from "../util";
import { Citation } from "./Markdown";

const Chart = lazy(() => import("./Chart"));

export interface GenieQuery {
  label: string;
  title?: string | null;
  description?: string | null;
  sql: string;
  row_count?: number | null;
  columns: { name: string; type?: string | null }[];
  rows: (string | null)[][];
  truncated: boolean;
}

export interface ChartSpec {
  time: boolean;
  x: string;
  series: string[];
  data: Record<string, string | number>[];
  rightAxis?: string;
}

/** A chart for Genie's rows when they have a category or time column and numbers: one line or bar per numeric
 *  column, or one per category when a second, small categorical column splits a single measure (for example
 *  failure rate per day and acquirer). */
export function chartSpec(q: GenieQuery): ChartSpec | null {
  const { columns } = q;
  if (q.rows.length < 2 || q.rows.length > 400 || columns.length < 2) return null;
  const numeric = columns.map((c, i) => ({ ...c, i })).filter((c) => isNumeric(c.type));
  if (!numeric.length) return null;
  let xi = columns.findIndex((c) => isTime(c.type));
  if (xi < 0) xi = columns.findIndex((c) => !isNumeric(c.type));
  if (xi < 0) return null;
  const time = isTime(columns[xi].type);
  // Genie often lists the newest first; a time axis reads oldest to newest (ISO values sort as text).
  const rows = time ? [...q.rows].sort((a, b) => String(a[xi] ?? "").localeCompare(String(b[xi] ?? ""))) : q.rows;
  const label = (v: string | null) => formatCell(v, columns[xi].type);
  const measures = numeric.filter((c) => c.i !== xi);
  if (!measures.length) return null;

  const split = columns.findIndex((c, i) => i !== xi && !isNumeric(c.type) && !isTime(c.type));
  const groups = split >= 0 ? [...new Set(rows.map((r) => r[split] ?? "—"))] : [];
  if (split >= 0 && measures.length === 1 && groups.length > 1 && groups.length <= 8) {
    const byX = new Map<string, Record<string, string | number>>();
    for (const r of rows) {
      const key = label(r[xi]);
      const point = byX.get(key) ?? { x: key };
      point[r[split] ?? "—"] = Number(r[measures[0].i]);
      byX.set(key, point);
    }
    return { time, x: columns[xi].name, series: groups as string[], data: [...byX.values()] };
  }

  const series = measures.slice(0, 3).map((c) => c.name);
  const data = rows.map((r) => {
    const point: Record<string, string | number> = { x: label(r[xi]) };
    measures.slice(0, 3).forEach((c) => (point[c.name] = Number(r[c.i])));
    return point;
  });
  const max = (name: string) => Math.max(...data.map((d) => Math.abs(Number(d[name]) || 0)));
  const rightAxis = series.length === 2 && max(series[0]) / (max(series[1]) || 1) > 20 ? series[1] : undefined;
  return { time, x: columns[xi].name, series, data, rightAxis };
}

function Table({ q }: { q: GenieQuery }) {
  return (
    <div className="scrollbar-thin max-h-80 overflow-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 bg-[#F4F1EC]">
          <tr>
            {q.columns.map((c) => (
              <th key={c.name} className={clsx("border-b border-line px-3 py-2 text-left font-semibold whitespace-nowrap", isNumeric(c.type) && "text-right")}>
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {q.rows.map((r, i) => (
            <tr key={i} className="odd:bg-white even:bg-paper/60">
              {r.map((v, j) => (
                <td key={j} className={clsx("border-b border-line/60 px-3 py-1.5 whitespace-nowrap", isNumeric(q.columns[j]?.type) && "text-right tabular-nums")}>
                  {formatCell(v, q.columns[j]?.type)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One query Genie ran: its result as a chart (when it charts), a table, or the SQL it wrote. */
export function QueryResult({ q }: { q: GenieQuery }) {
  const spec = useMemo(() => chartSpec(q), [q]);
  const [view, setView] = useState<"chart" | "table" | "sql">(spec ? "chart" : "table");
  const [copied, setCopied] = useState(false);
  const tabs = [
    ...(spec ? [{ id: "chart" as const, label: "Chart", icon: ChartColumn }] : []),
    { id: "table" as const, label: "Table", icon: Table2 },
    { id: "sql" as const, label: "SQL", icon: Code },
  ];
  const copy = async () => {
    await navigator.clipboard.writeText(q.sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="mt-3 rounded-2xl border border-line bg-paper/50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Citation label={q.label} />
        <span className="text-[13px] font-medium">{q.title || "Query result"}</span>
        <span className="text-[12px] text-muted">
          {q.rows.length.toLocaleString("en-SG")} row{q.rows.length === 1 ? "" : "s"}
          {q.truncated ? ` (first ${q.rows.length})` : ""}
        </span>
        <div className="ml-auto flex rounded-xl border border-line bg-white p-0.5">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setView(t.id)}
              className={clsx("inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-[12px] font-medium", view === t.id ? "bg-navy-900 text-white" : "text-muted hover:text-ink")}
            >
              <t.icon className="size-3.5" aria-hidden />
              {t.label}
            </button>
          ))}
        </div>
      </div>
      {q.description ? <p className="mb-2 text-[13px] text-muted">{q.description}</p> : null}
      {view === "chart" && spec ? (
        <Suspense fallback={<div className="grid h-72 place-items-center text-[13px] text-muted">Loading the chart…</div>}>
          <Chart spec={spec} />
        </Suspense>
      ) : null}
      {view === "table" ? (q.rows.length ? <Table q={q} /> : <p className="text-[13px] text-muted">No rows.</p>) : null}
      {view === "sql" ? (
        <div className="relative">
          <pre className="scrollbar-thin max-h-80 overflow-auto rounded-xl bg-navy-950 p-4 font-mono text-[12.5px] leading-relaxed text-[#E6EEF0]">{q.sql}</pre>
          <button type="button" onClick={copy} className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-lg bg-white/10 px-2 py-1 text-[11.5px] text-white hover:bg-white/20">
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            {copied ? "Copied" : "Copy SQL"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
