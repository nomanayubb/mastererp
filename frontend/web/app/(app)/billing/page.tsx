"use client";
import { useState } from "react";
import { Alert, Badge, Btn, Card, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Sub = { id: string; plan: string; plan_name: string; kind: string; status: string; period_end: string | null; trial_end: string | null; grace_end: string | null; cancel_at_period_end: boolean; pending_plan: string | null; access_until: string | null };
type Invoice = { id: string; number: string; kind: string; status: string; total: string; currency: string; due_at: string; paid_at: string | null; lines: { description: string; amount: string }[] };
type Overview = { subscriptions: Sub[]; invoices: Invoice[]; limits: Record<string, { used: number; limit: number | null }>; usage: Record<string, string> };
type Plan = { id: string; slug: string; name: string; description: string; kind: string; billing_period: string; currency: string; base_price: string; per_user_price: string; trial_days: number; features: string[]; limits: Record<string, number | null> };

const fmt = (d: string | null) => (d ? new Date(d).toLocaleDateString() : "—");
const tone = (s: string) => (s === "active" || s === "paid" ? "ok" : s === "trialing" ? "neutral" : s === "past_due" || s === "pending" || s === "open" ? "warn" : "danger");

export default function Billing() {
  const { can } = useAuth();
  const ov = useLoad(() => api<Overview>("/billing/overview"));
  const plans = useLoad(() => api<Plan[]>("/billing/plans"));
  const a = useAction();
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const manage = can("platform.billing.subscription", "create");
  const base = ov.data?.subscriptions.find((s) => s.kind === "base" && ["pending", "trialing", "active", "past_due"].includes(s.status));
  const reload = () => { ov.reload(); };

  const run = async (fn: () => Promise<unknown>, msg: string) => { await a.run(fn, msg); reload(); };

  return (
    <>
      <PageHeader title="Billing" subtitle="Your plan, usage and invoices." />
      {a.error && <div className="mb-3"><Alert>{a.error}</Alert></div>}
      {a.done && <div className="mb-3"><Alert kind="ok">{a.done}</Alert></div>}
      {ov.error && <Alert>{ov.error}</Alert>}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Subscription" className="xl:col-span-2">
          {!ov.data?.subscriptions.length ? <p className="text-sm text-muted">No subscription yet — pick a plan below.</p> : (
            <div className="space-y-4">
              {ov.data.subscriptions.map((s) => (
                <div key={s.id} className="rounded-md border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div><strong>{s.plan_name}</strong> <Badge>{s.kind}</Badge> <Badge tone={tone(s.status)}>{s.status.replace("_", " ")}</Badge></div>
                    <div className="text-xs text-muted">
                      {s.status === "trialing" ? `Trial ends ${fmt(s.trial_end)}` : s.status === "past_due" ? `Pay by ${fmt(s.grace_end)} to keep access` : s.status === "active" ? `Renews ${fmt(s.period_end)}` : ""}
                    </div>
                  </div>
                  {s.cancel_at_period_end && <p className="mt-2 text-xs text-warn">Cancels at the end of the period ({fmt(s.period_end)}).</p>}
                  {s.pending_plan && <p className="mt-2 text-xs text-muted">Switching to <strong>{s.pending_plan}</strong> at the next renewal.</p>}
                  {can("platform.billing.subscription", "edit") && ["active", "trialing"].includes(s.status) && (
                    <div className="mt-3 flex flex-wrap items-end gap-2">
                      <div className="min-w-48">
                        <Select label="Change plan" value={chosen[s.id] ?? ""} onChange={(e) => setChosen({ ...chosen, [s.id]: e.target.value })}>
                          <option value="">Select…</option>
                          {plans.data?.filter((p) => p.kind === s.kind && p.slug !== s.plan).map((p) => <option key={p.slug} value={p.slug}>{p.name} — {p.base_price} {p.currency}/{p.billing_period === "monthly" ? "mo" : "yr"}</option>)}
                        </Select>
                      </div>
                      <Btn variant="ghost" disabled={!chosen[s.id] || a.busy} onClick={() => run(() => api(`/billing/subscriptions/${s.id}/change-plan`, { body: { plan: chosen[s.id] } }), "Plan change requested")}>Apply</Btn>
                      {s.cancel_at_period_end
                        ? <Btn variant="ghost" onClick={() => run(() => api(`/billing/subscriptions/${s.id}/resume`, { body: {} }), "Subscription will continue")}>Keep subscription</Btn>
                        : can("platform.billing.subscription", "cancel") && <Btn variant="danger" onClick={() => confirm("Cancel at the end of the current period?") && run(() => api(`/billing/subscriptions/${s.id}/cancel`, { body: {} }), "Cancellation scheduled")}>Cancel</Btn>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Usage">
          <ul className="space-y-3 text-sm">
            {Object.entries(ov.data?.limits ?? {}).map(([k, v]) => {
              const pct = v.limit ? Math.min(100, Math.round((v.used / v.limit) * 100)) : 0;
              return (
                <li key={k}>
                  <div className="flex justify-between"><span className="capitalize">{k}</span><span className="text-muted">{v.used} / {v.limit ?? "unlimited"}</span></div>
                  {v.limit !== null && <div className="mt-1 h-1.5 rounded bg-bg" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${k} usage`}><div className={`h-1.5 rounded ${pct >= 90 ? "bg-danger" : "bg-brand"}`} style={{ width: `${pct}%` }} /></div>}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      <Card title="Invoices" className="mt-6">
        <Table
          head={["Number", "Type", "Amount", "Status", "Due", ""]}
          rows={(ov.data?.invoices ?? []).map((i) => [
            i.number, i.kind, `${i.total} ${i.currency}`, <Badge key="s" tone={tone(i.status)}>{i.status}</Badge>, fmt(i.due_at),
            i.status === "open" && can("platform.billing.invoices", "pay")
              ? <Btn key="p" disabled={a.busy} onClick={() => run(() => api(`/billing/invoices/${i.id}/pay`, { body: { payment_method: "test_ok" } }), `${i.number} paid (sandbox payment)`)}>Pay (sandbox)</Btn>
              : null,
          ])}
          empty="No invoices yet."
        />
        <p className="mt-3 text-xs text-muted">Payments run in a sandbox: no real card is charged. A live payment provider is not connected yet.</p>
      </Card>

      {manage && (
        <Card title="Available plans" className="mt-6">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {plans.data?.map((p) => (
              <div key={p.id} className="rounded-md border border-line p-3">
                <div className="flex items-center justify-between"><strong>{p.name}</strong><Badge>{p.kind}</Badge></div>
                <div className="mt-1 text-lg font-semibold">{p.base_price} <span className="text-xs font-normal text-muted">{p.currency}/{p.billing_period === "monthly" ? "mo" : "yr"}</span></div>
                {Number(p.per_user_price) > 0 && <div className="text-xs text-muted">+ {p.per_user_price} per user</div>}
                {p.trial_days > 0 && <div className="text-xs text-ok">{p.trial_days}-day free trial</div>}
                <p className="mt-2 text-xs text-muted">{p.description}</p>
                <ul className="mt-2 space-y-0.5 text-xs">
                  {Object.entries(p.limits).map(([k, v]) => <li key={k}>{v ?? "Unlimited"} {k}</li>)}
                  {p.features.map((f) => <li key={f}><code>{f}</code></li>)}
                </ul>
                {(p.kind === "addon" || !base) && (
                  <Btn className="mt-3" disabled={a.busy} onClick={() => run(() => api("/billing/subscriptions", { body: { plan: p.slug } }), `Subscribed to ${p.name}`)}>{p.kind === "addon" ? "Add" : "Choose plan"}</Btn>
                )}
              </div>
            ))}
            {!plans.data?.length && <p className="text-sm text-muted">No plans are published yet.</p>}
          </div>
        </Card>
      )}
    </>
  );
}
