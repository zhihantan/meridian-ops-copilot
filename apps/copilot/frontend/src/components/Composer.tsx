import { SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** The question box at the bottom of a chat page: Enter sends, Shift+Enter adds a line. */
export function Composer({ placeholder, busy, onSend, hint }: { placeholder: string; busy: boolean; onSend: (text: string) => void; hint?: string }) {
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
