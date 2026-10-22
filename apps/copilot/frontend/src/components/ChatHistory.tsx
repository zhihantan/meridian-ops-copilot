import clsx from "clsx";
import { History, Plus, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { ChatHistory, ChatSummary } from "../history";
import { Button, Spinner } from "./ui";

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

function dayOf(ms: number): string {
  const d = new Date(ms);
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, yesterday)) return "Yesterday";
  return d.toLocaleDateString("en-SG", { day: "numeric", month: "short" });
}

const timeOf = (ms: number) => new Date(ms).toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit", hour12: false });

/** A chat page's header buttons: its history, and a new chat (the open one stays in the history). */
export function ChatActions({ history, busy, empty, onShow }: { history: ChatHistory; busy: boolean; empty: boolean; onShow: () => void }) {
  return (
    <>
      <Button icon={History} onClick={onShow}>
        History
        {history.chats.length ? <span className="rounded-full bg-navy-100 px-1.5 text-[11px] font-semibold tabular-nums text-navy-900">{history.chats.length}</span> : null}
      </Button>
      <Button icon={Plus} disabled={busy || empty} title={busy ? "Wait for the answer to finish" : empty ? "This chat is already new" : undefined} onClick={history.newChat}>
        New chat
      </Button>
    </>
  );
}

/** The page's past chats, newest first, in a panel over the right of the page. Opening one continues it. */
export function ChatHistoryPanel({ history, open, onClose, busy, label }: { history: ChatHistory; open: boolean; onClose: () => void; busy: boolean; label: string }) {
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!open) {
      setConfirming(false);
      return;
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const groups: [string, ChatSummary[]][] = [];
  for (const chat of history.chats) {
    const day = dayOf(chat.updated);
    const last = groups[groups.length - 1];
    if (last && last[0] === day) last[1].push(chat);
    else groups.push([day, [chat]]);
  }

  return (
    <div className="absolute inset-0 z-40">
      <button type="button" aria-label="Close the history" onClick={onClose} className="absolute inset-0 cursor-default bg-navy-950/20" />
      <aside className="rise absolute right-0 top-0 flex h-full w-[380px] max-w-full flex-col border-l border-line bg-white shadow-[-12px_0_32px_rgba(27,49,57,0.16)]" aria-label={`${label} chat history`}>
        <div className="flex items-center gap-2 border-b border-line px-5 py-4">
          <History className="size-[18px] text-navy-900" aria-hidden />
          <p className="text-[15px] font-semibold">Chat history</p>
          <span className="text-[12.5px] text-muted">· {label}</span>
          <button type="button" onClick={onClose} aria-label="Close" className="ml-auto grid size-8 place-items-center rounded-lg text-muted hover:bg-black/5 hover:text-ink">
            <X className="size-4" aria-hidden />
          </button>
        </div>
        <div className="px-5 pt-4">
          <Button
            variant="primary"
            icon={Plus}
            className="w-full"
            disabled={busy}
            title={busy ? "Wait for the answer to finish" : undefined}
            onClick={() => {
              history.newChat();
              onClose();
            }}
          >
            New chat
          </Button>
          <p className="mt-2 text-[11.5px] leading-snug text-muted">Kept in this browser for you only, up to 30 chats. Opening one continues it where it left off.</p>
        </div>
        <div className="scrollbar-thin mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          {!history.ready ? (
            <p className="flex items-center gap-2 px-2 py-6 text-[13px] text-muted">
              <Spinner /> Checking who you are…
            </p>
          ) : !history.chats.length ? (
            <p className="px-4 py-8 text-center text-[13px] leading-relaxed text-muted">No chats yet. Ask a question, and the chat appears here.</p>
          ) : (
            groups.map(([day, chats]) => (
              <div key={day} className="mt-2">
                <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{day}</p>
                {chats.map((c) => {
                  const current = c.id === history.activeId;
                  return (
                    <div key={c.id} className={clsx("group flex items-start gap-1 rounded-xl px-2.5 py-2 transition", current ? "bg-navy-100/70" : "hover:bg-paper")}>
                      <button
                        type="button"
                        disabled={busy && !current}
                        title={busy && !current ? "Wait for the answer to finish" : undefined}
                        onClick={() => {
                          if (!current) history.open(c.id);
                          onClose();
                        }}
                        className="min-w-0 flex-1 text-left disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <p className="line-clamp-2 text-[13.5px] leading-snug text-ink">{c.title}</p>
                        <p className="mt-0.5 text-[11.5px] text-muted">
                          {c.questions} {c.questions === 1 ? "question" : "questions"} · {timeOf(c.updated)}
                          {current ? <span className="font-semibold text-navy-900"> · open now</span> : null}
                        </p>
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete the chat "${c.title}"`}
                        disabled={busy && current}
                        onClick={() => history.remove(c.id)}
                        className="grid size-7 shrink-0 place-items-center rounded-lg text-muted opacity-0 transition hover:bg-bad-soft hover:text-[#B42318] focus-visible:opacity-100 group-hover:opacity-100 disabled:invisible"
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                      </button>
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
        {history.chats.length ? (
          <div className="border-t border-line px-5 py-3">
            {confirming ? (
              <div className="flex items-center gap-2">
                <span className="mr-auto text-[12.5px] text-ink">Delete every {label} chat?</span>
                <Button variant="ghost" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    history.clear();
                    setConfirming(false);
                  }}
                >
                  Delete all
                </Button>
              </div>
            ) : (
              <Button variant="ghost" icon={Trash2} disabled={busy} onClick={() => setConfirming(true)}>
                Clear history
              </Button>
            )}
          </div>
        ) : null}
      </aside>
    </div>
  );
}
