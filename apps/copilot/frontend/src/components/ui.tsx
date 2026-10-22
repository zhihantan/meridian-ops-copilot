import clsx from "clsx";
import { LoaderCircle, RefreshCw, type LucideIcon } from "lucide-react";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Label = "native" | "preview" | "build";

const LABELS: Record<Label, string> = {
  native: "bg-ok text-white",
  preview: "bg-warn text-navy-900",
  build: "bg-[#5a6f77] text-white",
};

/** NATIVE, PREVIEW or BUILD, as every capability in this POC is labelled. */
export function Badge({ kind, children }: { kind: Label; children?: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold tracking-wide whitespace-nowrap", LABELS[kind])}>
      {kind.toUpperCase()}
      {children ? <span className="font-medium opacity-90">· {children}</span> : null}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={clsx("animate-spin", className ?? "size-4 text-info")} aria-hidden />;
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-2xl border border-line bg-white shadow-[0_1px_2px_rgba(27,49,57,0.05),0_6px_16px_rgba(27,49,57,0.04)]", className)}>{children}</div>;
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline" | "ok"; icon?: LucideIcon };

export function Button({ variant = "outline", icon: Icon, className, children, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      {...props}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-1.5 text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-brand text-white hover:bg-brand-dark shadow-sm",
        variant === "ok" && "bg-ok text-white hover:brightness-95 shadow-sm",
        variant === "outline" && "border border-line bg-white text-ink hover:border-navy-700/40 hover:bg-paper",
        variant === "ghost" && "text-muted hover:bg-black/5 hover:text-ink",
        className,
      )}
    >
      {Icon ? <Icon className="size-4" aria-hidden /> : null}
      {children}
    </button>
  );
}

const clock = (ms: number) => new Date(ms).toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

/**
 * Refresh, with the time the page last read its data. The data here is synthetic and stops on 15 Oct, so a refresh
 * usually returns the same rows: the spinning icon and the new time show that it ran.
 */
export function RefreshButton({ onRefresh, updated }: { onRefresh: () => Promise<unknown>; updated: number | null }) {
  const [busy, setBusy] = useState(false);
  const click = async () => {
    setBusy(true);
    try {
      await Promise.all([onRefresh(), new Promise((r) => setTimeout(r, 400))]); // long enough to see
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex items-center gap-2.5">
      {updated ? (
        <span className="text-[12px] tabular-nums text-muted" aria-live="polite">
          Updated {clock(updated)}
        </span>
      ) : null}
      <Button onClick={click} disabled={busy}>
        <RefreshCw className={clsx("size-4", busy && "animate-spin")} aria-hidden />
        {busy ? "Refreshing…" : "Refresh"}
      </Button>
    </div>
  );
}

export function Pill({ tone, children }: { tone: "ok" | "bad" | "warn" | "info" | "muted"; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-semibold",
        tone === "ok" && "bg-ok-soft text-[#067647]",
        tone === "bad" && "bg-bad-soft text-[#B42318]",
        tone === "warn" && "bg-warn-soft text-[#8A5A00]",
        tone === "info" && "bg-info-soft text-info",
        tone === "muted" && "bg-black/5 text-muted",
      )}
    >
      {children}
    </span>
  );
}

export function Tier({ name }: { name: string }) {
  return (
    <span className={clsx("rounded-full px-2 py-0.5 text-[11.5px] font-semibold", name === "finance" ? "bg-violet-soft text-violet" : "bg-navy-100 text-navy-900")}>
      {name}
    </span>
  );
}

export function Avatar({ text, className }: { text: string; className?: string }) {
  return <span className={clsx("grid shrink-0 place-items-center rounded-full font-bold", className ?? "size-9 bg-white text-navy-900 text-xs")}>{text}</span>;
}

export function PageHeader({ icon: Icon, title, subtitle, badges, actions }: { icon: LucideIcon; title: string; subtitle: string; badges?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center gap-4 border-b border-line bg-white/80 px-8 py-4 backdrop-blur">
      <span className="grid size-10 place-items-center rounded-xl bg-navy-900 text-white">
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="min-w-0">
        <h1 className="text-[17px] font-semibold leading-tight">{title}</h1>
        <p className="text-[13px] text-muted">{subtitle}</p>
      </div>
      {badges ? <div className="flex flex-wrap items-center gap-1.5">{badges}</div> : null}
      {actions ? <div className="ml-auto flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export interface Suggestion {
  kind: string;
  question: string;
  label?: string; // a short name for the chips above the question box
  tier?: string; // the knowledge tier it needs, shown on its chip
  followUp?: boolean; // only once a conversation has started
}

/** The empty state of a chat page: what it does, and questions that are known to work. */
export function Welcome({ icon: Icon, title, text, suggestions, onAsk }: { icon: LucideIcon; title: string; text: string; suggestions: Suggestion[]; onAsk: (q: string) => void }) {
  return (
    <div className="rise mx-auto max-w-3xl py-8">
      <span className="grid size-12 place-items-center rounded-2xl bg-brand text-white shadow-md shadow-brand/25">
        <Icon className="size-6" aria-hidden />
      </span>
      <h2 className="mt-5 text-2xl font-semibold tracking-tight">{title}</h2>
      <p className="mt-2 max-w-2xl text-[14.5px] text-muted">{text}</p>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {suggestions.filter((s) => !s.followUp).map((s) => (
          <button
            key={s.question}
            type="button"
            onClick={() => onAsk(s.question)}
            className="group rounded-2xl border border-line bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-navy-700/40 hover:shadow-md"
          >
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">{s.kind}</span>
            <span className="mt-1 block text-[14px] leading-snug text-ink">{s.question}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="rise flex justify-end">
      <div className="max-w-[78%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-navy-900 px-4 py-2.5 text-[14.5px] text-white shadow-sm">{text}</div>
    </div>
  );
}

export function BotCard({ icon: Icon, tone = "brand", children }: { icon: LucideIcon; tone?: "brand" | "info" | "violet"; children: ReactNode }) {
  return (
    <div className="rise flex items-start gap-3">
      <span className={clsx("mt-1 grid size-8 shrink-0 place-items-center rounded-full text-white", tone === "brand" && "bg-brand", tone === "info" && "bg-info", tone === "violet" && "bg-violet")}>
        <Icon className="size-4" aria-hidden />
      </span>
      <Card className="min-w-0 flex-1 rounded-tl-md px-5 py-4">{children}</Card>
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <p className="rounded-xl bg-bad-soft px-3 py-2 text-[13.5px] text-[#B42318]">{children}</p>;
}
