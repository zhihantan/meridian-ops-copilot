import clsx from "clsx";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CITE, type CiteKind, citeKind } from "../util";

const CHIP: Record<CiteKind, string> = {
  genie: "bg-brand-soft text-[#B42318] hover:bg-[#ffd9d1]",
  slack: "bg-violet-soft text-violet hover:bg-[#e3dbf8]",
  doc: "bg-navy-100 text-navy-900 hover:bg-[#d6e3e7]",
};

const TITLES: Record<CiteKind, string> = { genie: "Genie query", slack: "Slack message", doc: "Knowledge base passage" };

export function Citation({ label, onClick, active }: { label: string; onClick?: (label: string) => void; active?: boolean }) {
  const kind = citeKind(label);
  return (
    <button
      type="button"
      title={TITLES[kind]}
      onClick={onClick ? () => onClick(label) : undefined}
      className={clsx(
        "mx-0.5 inline-flex translate-y-[-1px] items-center rounded-md px-1.5 py-px align-middle text-[11px] font-semibold whitespace-nowrap transition",
        CHIP[kind],
        !onClick && "cursor-default",
        active && "ring-2 ring-warn",
      )}
    >
      {label}
    </button>
  );
}

/** Markdown from a model, with its citation labels as chips. Raw HTML is never rendered, and links are shown as
 *  plain text: the copilot is told never to link, and a planted link must not become clickable here. */
export function Markdown({ text, onCite, className }: { text: string; onCite?: (label: string) => void; className?: string }) {
  const marked = text.replace(CITE, (_, label: string) => `[${label}](cite:${encodeURIComponent(label)})`);
  return (
    <div className={clsx("md text-[14.5px] leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith("cite:") ? url : defaultUrlTransform(url))}
        components={{
          a: ({ href, children }) =>
            href?.startsWith("cite:") ? <Citation label={decodeURIComponent(href.slice(5))} onClick={onCite} /> : <span>{children}</span>,
          table: ({ children }) => (
            <div className="mb-2.5 overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
          img: () => null,
        }}
      >
        {marked}
      </ReactMarkdown>
    </div>
  );
}
