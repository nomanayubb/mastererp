"use client";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";

type Plan = { id: string; slug: string; name: string; kind: string; status: string; billing_period: string; currency: string; base_price: string; per_user_price: string; trial_days: number; is_default: boolean; features: string[]; limits: Record<string, number | null> };
type Sub = { tenant_slug: string; plan_slug: string; kind: string; status: string; current_period_end: string | null; grace_end: string | null };

const S = { realm: "staff" as const };
const tone = (s: string) => (s === "published" || s === "active" ? "ok" : s === "draft" || s === "trialing" ? "neutral" : s === "past_due" || s === "pending" ? "warn" : "danger");

export default function Plans() {
  const plans = useLoad(() => api<Plan[]>("/platform/plans", S));
  const subs = useLoad(() => api<Sub[]>("/platform/subscriptions", S));
  const a = useAction();
  const [f, setF] = useState({ slug: "", name: "", kind: "base", billing_period: "monthly", currency: "USD", base_price: "0", per_user_price: "0", trial_days: "0", is_default: false, features: "", users: "", companies: "", branches: "" });

  async function create(e: FormEvent) {
    e.preventDefault();
    const limits: Record<string, number> = {};
    for (const k of ["users", "companies", "branches"] as const) if (f[k] !== "") limits[k] = Number(f[k]);
    const body = { slug: f.slug, name: f.name, kind: f.kind, billing_period: f.billing_period, currency: f.currency, base_price: f.base_price, per_user_price: f.per_user_price, trial_days: Number(f.trial_days), is_default: f.is_default, features: f.features.split(",").map((s) => s.trim()).filter(Boolean), limits };
    const r = await a.run(() => api("/platform/plans", { ...S, body }), "Plan created (draft)");
    if (r) plans.reload();
  }
  const setStatus = async (p: Plan, status: string) => { await a.run(() => api(`/platform/plans/${p.id}/status`, { ...S, method: "PATCH", body: { status } })); plans.reload(); };
  const runBilling = async () => {
    const r = await a.run(() => api<Record<string, number>>("/platform/billing/run", { ...S, body: {} }));
    if (r) { await a.run(async () => r, `Billing run: ${JSON.stringify(r)}`); subs.reload(); }
  };

  return (
    <>
      <PageHeader title="Plans & billing" subtitle="Plans are immutable once published. Create a new plan to change pricing." actions={<Btn variant="ghost" onClick={runBilling} disabled={a.busy}>Run billing now</Btn>} />
      {a.error && <div className="mb-3"><Alert>{a.error}</Alert></div>}
      {a.done && <div className="mb-3"><Alert kind="ok">{a.done}</Alert></div>}
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card title="Plans">
            <Table
              head={["Plan", "Price", "Trial", "Limits", "Features", "Status", ""]}
              rows={(plans.data ?? []).map((p) => [
                <span key="n"><strong>{p.name}</strong> <code className="text-xs text-muted">{p.slug}</code>{p.is_default && <> <Badge tone="ok">default</Badge></>}<span className="block text-xs text-muted">{p.kind}</span></span>,
                <span key="p">{p.base_price} {p.currency}/{p.billing_period === "monthly" ? "mo" : "yr"}{Number(p.per_user_price) > 0 ? <span className="block text-xs text-muted">+ {p.per_user_price}/user</span> : null}</span>,
                p.trial_days ? `${p.trial_days}d` : "—",
                Object.entries(p.limits).map(([k, v]) => `${k}:${v ?? "∞"}`).join(", ") || "—",
                <code key="f" className="text-xs">{p.features.join(", ") || "—"}</code>,
                <Badge key="s" tone={tone(p.status)}>{p.status}</Badge>,
                p.status === "draft" ? <Btn key="b" variant="ghost" onClick={() => setStatus(p, "published")}>Publish</Btn> : p.status === "published" ? <Btn key="b" variant="danger" onClick={() => confirm(`Archive ${p.name}? Existing subscribers keep it.`) && setStatus(p, "archived")}>Archive</Btn> : null,
              ])}
              empty="No plans yet."
            />
          </Card>
          <Card title="Subscriptions (all tenants)">
            <Table head={["Tenant", "Plan", "Kind", "Status", "Period end", "Grace until"]} rows={(subs.data ?? []).map((s) => [<code key="t">{s.tenant_slug}</code>, s.plan_slug, s.kind, <Badge key="b" tone={tone(s.status)}>{s.status.replace("_", " ")}</Badge>, s.current_period_end ? new Date(s.current_period_end).toLocaleDateString() : "—", s.grace_end ? new Date(s.grace_end).toLocaleDateString() : "—"])} empty="No subscriptions yet." />
          </Card>
        </div>

        <Card title="New plan">
          <form onSubmit={create} className="space-y-3">
            <Field label="Slug" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value })} required placeholder="starter" />
            <Field label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
            <div className="grid grid-cols-2 gap-3">
              <Select label="Kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="base">Base</option><option value="addon">Add-on</option></Select>
              <Select label="Billing" value={f.billing_period} onChange={(e) => setF({ ...f, billing_period: e.target.value })}><option value="monthly">Monthly</option><option value="annual">Annual</option></Select>
              <Field label="Base price" type="number" min={0} step="0.01" value={f.base_price} onChange={(e) => setF({ ...f, base_price: e.target.value })} />
              <Field label="Per user" type="number" min={0} step="0.01" value={f.per_user_price} onChange={(e) => setF({ ...f, per_user_price: e.target.value })} />
              <Field label="Currency" maxLength={3} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} />
              <Field label="Trial days" type="number" min={0} value={f.trial_days} onChange={(e) => setF({ ...f, trial_days: e.target.value })} />
            </div>
            <Field label="Features (keys or patterns, comma-separated)" value={f.features} onChange={(e) => setF({ ...f, features: e.target.value })} placeholder="finance.*" />
            <div className="grid grid-cols-3 gap-3">
              <Field label="Max users" type="number" min={0} value={f.users} onChange={(e) => setF({ ...f, users: e.target.value })} />
              <Field label="Max companies" type="number" min={0} value={f.companies} onChange={(e) => setF({ ...f, companies: e.target.value })} />
              <Field label="Max branches" type="number" min={0} value={f.branches} onChange={(e) => setF({ ...f, branches: e.target.value })} />
            </div>
            <p className="text-xs text-muted">Leave a limit empty for unlimited.</p>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_default} onChange={(e) => setF({ ...f, is_default: e.target.checked })} /> Default plan for new tenants</label>
            <Btn type="submit" disabled={a.busy}>Create plan</Btn>
          </form>
        </Card>
      </div>
    </>
  );
}
