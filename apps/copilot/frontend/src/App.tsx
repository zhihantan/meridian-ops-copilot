import clsx from "clsx";
import { useCallback, useEffect, useState } from "react";

import { api, problem } from "./api";
import { Sidebar } from "./components/Sidebar";
import AboutPage from "./pages/About";
import ApprovalsPage from "./pages/Approvals";
import CopilotPage from "./pages/Copilot";
import GeniePage from "./pages/Genie";
import KnowledgePage from "./pages/Knowledge";
import OverviewPage from "./pages/Overview";
import type { Incoming, Me, Page, PendingApproval } from "./types";

const PAGES: Page[] = ["overview", "copilot", "genie", "knowledge", "approvals", "about"];

const fromHash = (): Page => {
  const p = window.location.hash.replace(/^#\/?/, "") as Page;
  return PAGES.includes(p) ? p : "overview";
};

export default function App() {
  const [page, setPage] = useState<Page>(fromHash);
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [incoming, setIncoming] = useState<Incoming | null>(null);

  useEffect(() => {
    const onHash = () => setPage(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = useCallback((p: Page) => {
    window.location.hash = `#/${p}`;
    setPage(p);
  }, []);

  useEffect(() => {
    api<Me>("/api/me")
      .then(setMe)
      .catch((e) => setMeError(problem(e)));
  }, []);

  const refreshPending = useCallback(async () => {
    try {
      const r = await api<{ approvals: PendingApproval[] }>("/api/approvals");
      setPending(r.approvals);
    } catch {
      /* keep the last list; the Approvals page shows its own errors */
    }
  }, []);

  // Admins see refunds waiting for approval appear within 20 seconds, wherever they are in the console.
  useEffect(() => {
    if (!me?.admin) return;
    refreshPending();
    const timer = setInterval(() => document.visibilityState === "visible" && refreshPending(), 20_000);
    return () => clearInterval(timer);
  }, [me?.admin, refreshPending]);

  const ask = useCallback(
    (p: Page, question: string) => {
      setIncoming({ page: p, question, nonce: Date.now() });
      navigate(p);
    },
    [navigate],
  );

  // Every page stays mounted, so a running answer keeps streaming while you look elsewhere.
  const view = (p: Page) => {
    switch (p) {
      case "overview":
        return <OverviewPage me={me} pending={pending} onAsk={ask} navigate={navigate} />;
      case "copilot":
        return <CopilotPage incoming={incoming} owner={me?.id ?? null} />;
      case "genie":
        return <GeniePage incoming={incoming} owner={me?.id ?? null} />;
      case "knowledge":
        return <KnowledgePage incoming={incoming} owner={me?.id ?? null} />;
      case "approvals":
        return <ApprovalsPage me={me} pending={pending} refreshPending={refreshPending} active={page === "approvals"} />;
      case "about":
        return <AboutPage active={page === "about"} navigate={navigate} />;
    }
  };

  return (
    <div className="flex h-full">
      <Sidebar page={page} navigate={navigate} me={me} meError={meError} pendingCount={pending?.length ?? 0} />
      <main className="relative min-w-0 flex-1">
        {PAGES.map((p) => (
          <section key={p} className={clsx("absolute inset-0 flex flex-col", page !== p && "hidden")} aria-hidden={page !== p}>
            {view(p)}
          </section>
        ))}
      </main>
    </div>
  );
}
