// Chat history for the console's chat pages (BUILD). A page keeps its open chat in the tab (sessionStorage), so a
// reload resumes an answer that is still running. Once a chat has a question, it is also copied into this browser's
// localStorage under the signed-in person's id, so New chat keeps the previous chat and History can open it again.
// Nothing leaves the browser: a chat stays where it was asked until it is deleted. It is not checked again against
// the person's current access; opening it shows what they were shown at the time.
import { useCallback, useEffect, useRef, useState } from "react";

import { uid, useSessionState } from "./util";

const MAX_CHATS = 30; // per page and person; the oldest go first

export interface ChatSummary {
  id: string;
  title: string; // the first question
  questions: number;
  created: number;
  updated: number;
}

interface Saved<S> extends ChatSummary {
  state: S;
}

function load<S>(key: string): Saved<S>[] {
  try {
    const list = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

/** Save the list, dropping the oldest chats while the browser's storage is full. */
function store<S>(key: string, list: Saved<S>[]): Saved<S>[] {
  let kept = list.slice(0, MAX_CHATS);
  for (;;) {
    try {
      if (kept.length) localStorage.setItem(key, JSON.stringify(kept));
      else localStorage.removeItem(key);
      return kept;
    } catch {
      if (kept.length <= 1) return kept; // not even one fits: it stays on this page until a reload
      kept = kept.slice(0, -1);
    }
  }
}

export interface ChatHistory {
  ready: boolean; // the person is known and their history is loaded
  activeId: string;
  chats: ChatSummary[]; // newest activity first
  newChat: () => void;
  open: (id: string) => void;
  remove: (id: string) => void;
  clear: () => void;
}

/**
 * The history of one chat page. `state` and `setState` are the page's open chat; `fresh` makes an empty one, and
 * `settle` closes any answer a saved chat was still waiting for, since that wait ended with the page that started it.
 */
export function useChatHistory<S extends { turns: { question: string }[] }>(
  page: string,
  owner: string | null,
  state: S,
  setState: (s: S) => void,
  fresh: () => S,
  settle: (s: S) => S,
): ChatHistory {
  const [activeId, setActiveId] = useSessionState<string>(`meridian.${page}.chat`, uid);
  const key = owner ? `meridian.history.${page}.${owner}` : null;
  const [list, setList] = useState<Saved<S>[]>([]);
  const live = useRef({ key, list, activeId, state });
  live.current = { key, list, activeId, state };

  useEffect(() => {
    if (!key) return;
    setList(load<S>(key));
    const onStorage = (e: StorageEvent) => e.key === key && setList(load<S>(key)); // another tab changed it
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key]);

  // Copy the open chat into the history once it has a question, and again whenever it changes.
  const save = useCallback(() => {
    const { key, list, activeId, state } = live.current;
    if (!key || !state.turns.length) return;
    const existing = list.find((c) => c.id === activeId);
    if (existing && JSON.stringify(existing.state) === JSON.stringify(state)) return;
    const now = Date.now();
    const record: Saved<S> = { id: activeId, title: state.turns[0].question, questions: state.turns.length, created: existing?.created ?? now, updated: now, state };
    const next = store(key, [record, ...list.filter((c) => c.id !== activeId)]);
    live.current.list = next;
    setList(next);
  }, []);

  useEffect(() => {
    const timer = setTimeout(save, 400); // answers stream in many small updates
    return () => clearTimeout(timer);
  }, [key, activeId, state, save]);

  useEffect(() => {
    window.addEventListener("pagehide", save); // closing the tab inside that pause still saves
    return () => window.removeEventListener("pagehide", save);
  }, [save]);

  const start = useCallback(() => {
    setActiveId(uid());
    setState(fresh());
  }, [setActiveId, setState, fresh]);

  const newChat = useCallback(() => {
    save();
    start();
  }, [save, start]);

  const open = useCallback(
    (id: string) => {
      save();
      const chat = live.current.list.find((c) => c.id === id);
      if (!chat) return;
      setActiveId(chat.id);
      setState(settle(chat.state));
    },
    [save, setActiveId, setState, settle],
  );

  const remove = useCallback(
    (id: string) => {
      const { key, list, activeId } = live.current;
      if (key) {
        const next = store(key, list.filter((c) => c.id !== id));
        live.current.list = next;
        setList(next);
      }
      if (id === activeId) start();
    },
    [start],
  );

  const clear = useCallback(() => {
    const { key } = live.current;
    if (key) {
      live.current.list = store(key, []);
      setList([]);
    }
    start();
  }, [start]);

  return {
    ready: Boolean(key),
    activeId,
    chats: list.map(({ id, title, questions, created, updated }) => ({ id, title, questions, created, updated })),
    newChat,
    open,
    remove,
    clear,
  };
}
