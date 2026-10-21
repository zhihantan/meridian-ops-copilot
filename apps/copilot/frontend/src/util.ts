import { useEffect, useState } from "react";

export const uid = () => crypto.randomUUID();

export const money = (v: unknown) =>
  Number(v).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const pct = (v: unknown, digits = 1) => `${(Number(v) * 100).toFixed(digits)}%`;

export const count = (v: unknown) => Number(v).toLocaleString("en-SG");

export function initials(name: string): string {
  const parts = name.split(/[\s._@-]+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2)).toUpperCase();
}

/** Citation labels as the copilot and the knowledge chatbot write them: [DOC-RB-014 p.1], [GENIE-1a2b3c4d]. */
export const CITE = /\[(GENIE-[0-9a-f]{8}|[A-Z][A-Z0-9-]+ p\.\d+)\]/g;

export function citations(text: string): string[] {
  return [...new Set([...text.matchAll(CITE)].map((m) => m[1]))];
}

export type CiteKind = "genie" | "slack" | "doc";

export const citeKind = (label: string): CiteKind =>
  label.startsWith("GENIE-") ? "genie" : label.startsWith("SLACK-") ? "slack" : "doc";

export const isNumeric = (type?: string | null) => /INT|LONG|SHORT|BYTE|DOUBLE|FLOAT|DECIMAL|NUMBER/i.test(type ?? "");

export const isTime = (type?: string | null) => /DATE|TIMESTAMP/i.test(type ?? "");

export function formatCell(value: string | null, type?: string | null): string {
  if (value === null || value === undefined) return "—";
  if (isNumeric(type)) {
    const n = Number(value);
    if (Number.isFinite(n)) return n.toLocaleString("en-SG", { maximumFractionDigits: 4 });
  }
  if (isTime(type)) return value.replace("T", " ").replace(/(:\d\d)\.\d+Z?$/, "$1").replace(/Z$/, "");
  return value;
}

/** State kept in this browser tab only (sessionStorage), so a reload keeps the conversation. */
export function useSessionState<T>(key: string, initial: () => T) {
  const [state, setState] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial();
    } catch {
      return initial();
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(state));
    } catch {
      /* storage full: the conversation still works, it just won't survive a reload */
    }
  }, [key, state]);
  return [state, setState] as const;
}

/** The current time, ticking while active, for elapsed-time displays. */
export function useNow(active: boolean, ms = 500): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
  return now;
}
