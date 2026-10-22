import clsx from "clsx";
import { SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Suggestion } from "./ui";

/**
 * The question box at the bottom of a chat page: Enter sends, Shift+Enter adds a line. Example questions, when given,
 * sit above it as chips that ask at once; hovering one shows the whole question.
 */
export function Composer({ placeholder, busy, onSend, hint, examples }: { placeholder: string; busy: boolean; onSend: (text: string) => void; hint?: string; examples?: Suggestion[] }) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  const send = () => {
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    onSend(q);
  };

  return (
    <div className="border-t border-line bg-white/90 px-8 pb-4 pt-3 backdrop-blur">
      <div className="mx-auto max-w-4xl">
        {examples?.length ? (
          <div className="mb-2.5 flex flex-wrap items-center gap-1.5" aria-label="Example questions">
            <span className="mr-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">Try</span>
            {examples.map((e) => (
              <button
                key={e.question}
                type="button"
                disabled={busy}
                onClick={() => onSend(e.question)}
                aria-label={`Ask: ${e.question}`}
                className="group relative inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-[12.5px] text-ink shadow-sm transition hover:-translate-y-px hover:border-navy-700/40 hover:shadow disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
              >
                {e.label ?? e.question}
                {e.tier ? <span className={clsx("rounded-full px-1.5 text-[10.5px] font-semibold", e.tier === "finance" ? "bg-violet-soft text-violet" : "bg-navy-100 text-navy-900")}>{e.tier}</span> : null}
                <span className="pointer-events-none absolute bottom-full left-0 z-20 mb-2 w-max max-w-[340px] rounded-lg bg-navy-900 px-2.5 py-1.5 text-left text-[12px] leading-snug text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                  {e.question}
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-paper p-2 shadow-sm focus-within:border-navy-700/50 focus-within:bg-white focus-within:ring-4 focus-within:ring-navy-100">
          <textarea
            ref={box}
            rows={1}
            value={text}
            placeholder={placeholder}
            aria-label={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            className="max-h-44 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[14.5px] outline-none placeholder:text-muted/70"
          />
          <button
            type="button"
            onClick={send}
            disabled={busy || !text.trim()}
            aria-label="Send"
            className="grid size-10 place-items-center rounded-xl bg-brand text-white shadow-sm transition hover:bg-brand-dark disabled:opacity-40"
          >
            <SendHorizontal className="size-4.5" aria-hidden />
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[11.5px] text-muted">{hint ?? "Enter to send · Shift+Enter for a new line"}</p>
      </div>
    </div>
  );
}
