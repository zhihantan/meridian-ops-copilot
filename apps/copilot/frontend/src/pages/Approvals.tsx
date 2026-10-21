import { BadgeCheck, Hourglass, RefreshCw, ShieldCheck, ShieldX } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, post, problem } from "../api";
import { Badge, Button, Card, ErrorNote, PageHeader, Pill } from "../components/ui";
import type { DecidedApproval, Me, PendingApproval } from "../types";
import { count, money } from "../util";

// Refund approvals (T18): the copilot's runbook stops at s5 for a batch above SGD 500. A member of meridian-admin
// approves here or in SQL; both call agent.approve_refund, which alone decides.

function expiresIn(minutes: string): string {
  const m = Math.max(0, Number(minutes) || 0);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
}

function ApproveDialog({ approval, onClose, onDone }: { approval: PendingApproval; onClose: () => void; onDone: (ok: boolean, text: string) => void }) {
  const [reason, setReason] = useState("Approved after checking the impact");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await post<{ approved: boolean; reason?: string }>(`/api/approvals/${encodeURIComponent(approval.approval_id)}`, { reason }, { "X-Meridian-UI": "1" });
      onDone(r.approved, r.approved ? `Approved ${approval.batch_id}. The requester can now continue the run, and step s6 executes the refund.` : `${approval.batch_id}: refused by the procedure: ${r.reason}`);
    } catch (e) {
      onDone(false, `${approval.batch_id}: ${problem(e)}`);
    }
    setBusy(false);
  };
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-navy-950/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
      <Card className="rise w-full max-w-md p-6">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-ok-soft text-[#067647]">
            <ShieldCheck className="size-5" />
          </span>
          <div>
            <h2 className="text-[16px] font-semibold">Approve this refund batch?</h2>
            <p className="text-[13px] text-muted">
              {approval.batch_id} · {approval.acquirer_id} · requested by {approval.requested_by}
            </p>
          </div>
        </div>
        <div className="mt-5 rounded-xl bg-paper px-4 py-3">
          <p className="text-[24px] font-semibold tracking-tight">SGD {money(approval.total_sgd)}</p>
          <p className="text-[13px] text-muted">{approval.payments ? `${count(approval.payments)} refundable failed payments` : ""}</p>
        </div>
        <label className="mt-4 block text-[12.5px] font-medium text-muted" htmlFor="reason">
          Reason, for the audit log
        </label>
        <input id="reason" name="reason" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px] outline-none focus:border-navy-700/50 focus:ring-4 focus:ring-navy-100" />
        <p className="mt-3 text-[12.5px] text-muted">The procedure checks that you are in meridian-admin, that you did not request it, and that it has not expired.</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="ok" icon={BadgeCheck} disabled={busy || !reason.trim()} onClick={submit}>
            {busy ? "Approving…" : "Approve"}
          </Button>
        </div>
      </Card>
    </div>
  );
}

export default function ApprovalsPage({ me, pending, refreshPending, active }: { me: Me | null; pending: PendingApproval[] | null; refreshPending: () => Promise<void>; active: boolean }) {
  const [decided, setDecided] = useState<DecidedApproval[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<PendingApproval | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api<{ approvals: DecidedApproval[]; error?: string }>("/api/approvals/recent");
      setDecided(r.approvals);
      setError(r.error ?? null);
    } catch (e) {
      setError(problem(e));
    }
    await refreshPending();
  }, [refreshPending]);

  useEffect(() => {
    if (active && me?.admin) refresh();
  }, [active, me?.admin, refresh]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={ShieldCheck}
        title="Approvals"
        subtitle="Refund batches above SGD 500 wait here for an admin who is not the requester"
        badges={<Badge kind="build">procedures in Unity Catalog</Badge>}
        actions={me?.admin ? <Button icon={RefreshCw} onClick={refresh}>Refresh</Button> : null}
      />
      <div className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-5xl space-y-6">
          {!me ? <p className="text-muted">Checking who you are…</p> : null}
          {me && !me.admin ? (
            <Card className="flex items-center gap-4 p-6">
              <ShieldX className="size-8 text-muted" />
              <div>
                <p className="font-semibold">Only meridian-admin can approve refunds</p>
                <p className="text-[13.5px] text-muted">Your runs still stop at the approval step; an admin approves them here or in SQL.</p>
              </div>
            </Card>
          ) : null}
          {note ? <p className={note.ok ? "rounded-xl bg-ok-soft px-4 py-2.5 text-[13.5px] text-[#067647]" : "rounded-xl bg-bad-soft px-4 py-2.5 text-[13.5px] text-[#B42318]"}>{note.text}</p> : null}
          {error ? <ErrorNote>{error}</ErrorNote> : null}
          {me?.admin ? (
            <>
              <section>
                <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
                  <Hourglass className="size-4 text-[#B7791F]" /> Waiting for approval
                  {pending?.length ? <Pill tone="warn">{pending.length}</Pill> : null}
                </h2>
                {!pending ? <p className="text-[13.5px] text-muted">Loading…</p> : null}
                {pending && !pending.length ? (
                  <Card className="p-6 text-center text-[14px] text-muted">No refund batch is waiting for approval. When a runbook run reaches s5 above SGD 500, it appears here within 20 seconds.</Card>
                ) : null}
                <div className="grid gap-3 md:grid-cols-2">
                  {pending?.map((a) => {
                    const mine = String(a.mine) === "true";
                    return (
                      <Card key={a.approval_id} className="p-5">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-[24px] font-semibold tracking-tight">SGD {money(a.total_sgd)}</p>
                            <p className="text-[13px] text-muted">{a.payments ? `${count(a.payments)} payments · ` : ""}{a.acquirer_id}</p>
                          </div>
                          <Pill tone="warn">expires in {expiresIn(a.expires_in_minutes)}</Pill>
                        </div>
                        <p className="mt-3 text-[13.5px]">
                          Refund batch <code className="rounded bg-paper px-1 font-mono text-[12.5px]">{a.batch_id}</code>
                        </p>
                        <p className="text-[13px] text-muted">
                          Requested by {a.requested_by}, {a.requested_sgt} SGT
                        </p>
                        {mine ? (
                          <p className="mt-4 rounded-xl bg-paper px-3 py-2 text-[13px] text-muted">You requested this one, so only another admin can approve it.</p>
                        ) : (
                          <Button variant="ok" icon={BadgeCheck} className="mt-4 w-full py-2" onClick={() => setDialog(a)}>
                            Review and approve
                          </Button>
                        )}
                      </Card>
                    );
                  })}
                </div>
              </section>
              <section>
                <h2 className="mb-3 text-[15px] font-semibold">Recently decided</h2>
                <Card className="overflow-hidden">
                  <table className="w-full text-[13px]">
                    <thead className="bg-[#F4F1EC] text-left">
                      <tr>
                        {["Batch", "Acquirer", "Amount", "Payments", "Requested by", "Decision", "Approved by", "Decided (SGT)", "Executed (SGT)"].map((h) => (
                          <th key={h} className="px-3 py-2 font-semibold whitespace-nowrap">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {decided?.map((d) => (
                        <tr key={d.approval_id} className="border-t border-line/70">
                          <td className="px-3 py-2 font-mono text-[12px]">{d.batch_id}</td>
                          <td className="px-3 py-2">{d.acquirer_id}</td>
                          <td className="px-3 py-2 tabular-nums">SGD {money(d.total_sgd)}</td>
                          <td className="px-3 py-2 tabular-nums">{d.payments ? count(d.payments) : "—"}</td>
                          <td className="px-3 py-2">{d.requested_by}</td>
                          <td className="px-3 py-2">
                            <Pill tone={d.status === "approved" ? "ok" : d.status === "expired" ? "muted" : "bad"}>{d.status}</Pill>
                          </td>
                          <td className="px-3 py-2">{d.approved_by || "—"}</td>
                          <td className="px-3 py-2 whitespace-nowrap">{d.decided_sgt ?? "—"}</td>
                          <td className="px-3 py-2 whitespace-nowrap">{d.batch_status === "executed" ? d.executed_sgt : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {decided && !decided.length ? <p className="p-4 text-center text-[13.5px] text-muted">No decided approvals yet.</p> : null}
                  {!decided ? <p className="p-4 text-center text-[13.5px] text-muted">Loading…</p> : null}
                </Card>
              </section>
            </>
          ) : null}
        </div>
      </div>
      {dialog ? (
        <ApproveDialog
          approval={dialog}
          onClose={() => setDialog(null)}
          onDone={(ok, text) => {
            setDialog(null);
            setNote({ ok, text });
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}
