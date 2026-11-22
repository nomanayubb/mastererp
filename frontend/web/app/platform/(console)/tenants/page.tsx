"use client";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";

type Tenant = { id: string; slug: string; name: string; status: string; created_at: string };
type Ent = { feature_key: string; expires_at: string | null };

const S = { realm: "staff" as const };

export default function Tenants() {
  const tenants = useLoad(() => api<Tenant[]>("/platform/tenants", S));
  const [sel, setSel] = useState<Tenant | null>(null);
  const ents = useLoad(() => (sel ? api<Ent[]>(`/platform/tenants/${sel.id}/entitlements`, S) : Promise.resolve([])), [sel?.id]);
  const [key, setKey] = useState("");
  const act = useAction();

  async function setStatus(t: Tenant, status: string) {
    await act.run(() => api(`/platform/tenants/${t.id}/status`, { ...S, body: { status } }));
    tenants.reload();
    if (sel?.id === t.id) setSel({ ...t, status });
  }
  async function grant(e: FormEvent) {
    e.preventDefault();
    const r = await act.run(() => api(`/platform/tenants/${sel!.id}/entitlements`, { ...S, body: { feature_key: key } }), "Entitlement granted");
    if (r !== null) { setKey(""); ents.reload(); }
  }

  return (
    <>
      <PageHeader title="Tenants" subtitle="Metadata only — platform staff cannot read tenants’ business data." />
      {tenants.error && <Alert>{tenants.error}</Alert>}
      {act.error && <div className="mb-3"><Alert>{act.error}</Alert></div>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="All tenants">
          <Table
            head={["Name", "Slug", "Status", ""]}
            rows={(tenants.data ?? []).map((t) => [
              t.name, <code key="s">{t.slug}</code>,
              <Badge key="b" tone={t.status === "active" ? "ok" : "warn"}>{t.status}</Badge>,
              <div key="a" className="flex gap-2">
                <Btn variant="ghost" onClick={() => setSel(t)}>Entitlements</Btn>
                {t.status === "active"
                  ? <Btn variant="danger" onClick={() => confirm(`Suspend ${t.name}? All their users are locked out.`) && setStatus(t, "suspended")}>Suspend</Btn>
                  : <Btn variant="ghost" onClick={() => setStatus(t, "active")}>Activate</Btn>}
              </div>,
            ])}
          />
        </Card>
        <Card title={sel ? `Entitlements — ${sel.name}` : "Entitlements"}>
          {!sel ? <p className="text-sm text-muted">Pick a tenant.</p> : (
            <>
              <p className="mb-3 text-xs text-muted">The platform kernel is always on. Other applications need an entitlement (e.g. <code>finance.*</code>).</p>
              <Table
                head={["Feature pattern", "Expires", ""]}
                rows={(ents.data ?? []).map((e) => [<code key="k">{e.feature_key}</code>, e.expires_at ? new Date(e.expires_at).toLocaleString() : "Never",
                  <Btn key="r" variant="danger" onClick={async () => { await act.run(() => api(`/platform/tenants/${sel.id}/entitlements?feature_key=${encodeURIComponent(e.feature_key)}`, { ...S, method: "DELETE" })); ents.reload(); }}>Revoke</Btn>])}
                empty="No entitlements — only platform services are available."
              />
              <form onSubmit={grant} className="mt-4 flex items-end gap-3 border-t border-line pt-4">
                <div className="flex-1"><Field label="Grant (feature key or pattern)" value={key} onChange={(e) => setKey(e.target.value)} placeholder="finance.*" required /></div>
                <Btn type="submit" disabled={act.busy}>Grant</Btn>
              </form>
              {act.done && <div className="mt-3"><Alert kind="ok">{act.done}</Alert></div>}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
