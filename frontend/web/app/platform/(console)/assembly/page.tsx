"use client";
import { useMemo, useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";

type Tpl = { id: string; slug: string; name: string; version: number; status: string; industry: string; parent_id: string | null; config: Record<string, unknown> };
type Industry = { slug: string; name: string };
type Feature = { key: string };
type Version = { version: number; status: string; composition: { modules?: string[]; template?: string; plans?: string[]; branding?: { name?: string; primary_color?: string } } };
type Product = { slug: string; name: string; status: string; industry: string | null; versions: Version[] };
type Resolved = { modules: string[]; added_dependencies: string[]; warnings: string[] };

const S = { realm: "staff" as const };
const tone = (s: string) => (s === "published" ? "ok" : s === "draft" ? "neutral" : "warn");

export default function Assembly() {
  const tpls = useLoad(() => api<Tpl[]>("/platform/templates", S));
  const inds = useLoad(() => api<Industry[]>("/platform/registry/industries", S));
  const feats = useLoad(() => api<Feature[]>("/platform/registry/features", S));
  const prods = useLoad(() => api<Product[]>("/platform/products", S));
  const a = useAction();
  const modules = useMemo(() => [...new Set((feats.data ?? []).map((f) => f.key.split(".").slice(0, 2).join(".")).filter((m) => !m.startsWith("platform.")))].sort(), [feats.data]);

  const [nt, setNt] = useState({ industry: "", slug: "", name: "", parent: "", config: '{\n  "modules": [],\n  "terminology": {}\n}' });
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [resolved, setResolved] = useState<string | null>(null);
  const [np, setNp] = useState({ slug: "", name: "", description: "" });
  const [sel, setSel] = useState<{ slug: string; version: number } | null>(null);
  const [comp, setComp] = useState<{ modules: string[]; template: string; plans: string; name: string; color: string }>({ modules: [], template: "", plans: "", name: "", color: "" });
  const [checked, setChecked] = useState<Resolved | null>(null);

  const published = (tpls.data ?? []).filter((t) => t.status === "published");
  const json = (text: string) => { try { return JSON.parse(text); } catch { throw new Error("Config is not valid JSON"); } };

  async function createTemplate(e: FormEvent) {
    e.preventDefault();
    const r = await a.run(() => api("/platform/templates", { ...S, body: { industry: nt.industry, slug: nt.slug, name: nt.name, parent: nt.parent || null, config: json(nt.config) } }), "Template created (draft)");
    if (r) tpls.reload();
  }
  const setStatus = async (t: Tpl, status: string) => { await a.run(() => api(`/platform/templates/${t.id}/status`, { ...S, method: "PATCH", body: { status } })); tpls.reload(); };
  const saveConfig = async () => { if (!editing) return; const ok = await a.run(async () => { await api(`/platform/templates/${editing.id}/config`, { ...S, method: "PUT", body: { config: json(editing.text) } }); return true; }, "Config saved"); if (ok) { setEditing(null); tpls.reload(); } };
  const newVersion = async (t: Tpl) => { await a.run(() => api(`/platform/templates/${t.slug}/versions`, { ...S, body: {} }), "New draft version created"); tpls.reload(); };
  const showResolved = async (t: Tpl) => { const r = await a.run(() => api<unknown>(`/platform/templates/${t.slug}/resolved`, S)); if (r) setResolved(JSON.stringify(r, null, 2)); };

  async function createProduct(e: FormEvent) {
    e.preventDefault();
    const r = await a.run(() => api("/platform/products", { ...S, body: { slug: np.slug, name: np.name, description: np.description } }), "Product created (draft v1)");
    if (r) prods.reload();
  }
  const pick = (p: Product, v: Version) => {
    setSel({ slug: p.slug, version: v.version });
    setChecked(null);
    setComp({ modules: v.composition.modules ?? [], template: v.composition.template ?? "", plans: (v.composition.plans ?? []).join(","), name: v.composition.branding?.name ?? "", color: v.composition.branding?.primary_color ?? "" });
  };
  const body = () => ({ modules: comp.modules, ...(comp.template ? { template: comp.template } : {}), plans: comp.plans.split(",").map((s) => s.trim()).filter(Boolean), branding: { ...(comp.name ? { name: comp.name } : {}), ...(comp.color ? { primary_color: comp.color } : {}) } });
  const saveComp = async () => { if (!sel) return; const r = await a.run(() => api<Resolved>(`/platform/products/${sel.slug}/versions/${sel.version}/composition`, { ...S, method: "PUT", body: { composition: body() } }), "Composition saved"); if (r) { setChecked(r); prods.reload(); } };
  const test = async () => { if (!sel) return; const r = await a.run(() => api<Resolved>(`/platform/products/${sel.slug}/versions/${sel.version}/test`, { ...S, body: {} })); if (r) setChecked(r); };
  const publish = async () => { if (!sel) return; await a.run(() => api(`/platform/products/${sel.slug}/versions/${sel.version}/publish`, { ...S, body: {} }), "Version published (now immutable)"); prods.reload(); };
  const newPv = async (slug: string) => { await a.run(() => api(`/platform/products/${slug}/versions`, { ...S, body: {} }), "New draft version created"); prods.reload(); };
  const selVersion = prods.data?.find((p) => p.slug === sel?.slug)?.versions.find((v) => v.version === sel?.version);

  return (
    <>
      <PageHeader title="Templates & software editions" subtitle="Industry templates inherit from parents. Editions assemble existing modules — nothing is duplicated. Published versions are immutable." />
      {a.error && <div className="mb-3"><Alert>{a.error}</Alert></div>}
      {a.done && <div className="mb-3"><Alert kind="ok">{a.done}</Alert></div>}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Industry templates" className="xl:col-span-2">
          <Table head={["Template", "Industry", "Status", ""]} rows={(tpls.data ?? []).map((t) => [
            <span key="n"><strong>{t.name}</strong> <code className="text-xs text-muted">{t.slug}@{t.version}</code></span>, t.industry, <Badge key="s" tone={tone(t.status)}>{t.status}</Badge>,
            <div key="b" className="flex flex-wrap gap-2">
              <Btn variant="ghost" onClick={() => showResolved(t)}>Resolved</Btn>
              {t.status === "draft" && <><Btn variant="ghost" onClick={() => setEditing({ id: t.id, text: JSON.stringify(t.config, null, 2) })}>Edit config</Btn><Btn onClick={() => setStatus(t, "published")}>Publish</Btn></>}
              {t.status === "published" && <Btn variant="ghost" onClick={() => newVersion(t)}>New version</Btn>}
            </div>])} empty="No templates yet." />
          {editing && <div className="mt-4 space-y-2 border-t border-line pt-4"><textarea aria-label="Template config JSON" className="h-56 w-full rounded-md border border-line bg-surface p-2 font-mono text-xs" value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} /><div className="flex gap-2"><Btn onClick={saveConfig}>Save</Btn><Btn variant="ghost" onClick={() => setEditing(null)}>Cancel</Btn></div></div>}
          {resolved && <pre className="mt-4 max-h-72 overflow-auto rounded-md border border-line bg-bg p-2 text-xs">{resolved}</pre>}
        </Card>
        <Card title="New template">
          <form onSubmit={createTemplate} className="space-y-3">
            <Select label="Industry" value={nt.industry} onChange={(e) => setNt({ ...nt, industry: e.target.value })} required><option value="">Select…</option>{inds.data?.map((i) => <option key={i.slug} value={i.slug}>{i.name}</option>)}</Select>
            <Field label="Slug" value={nt.slug} onChange={(e) => setNt({ ...nt, slug: e.target.value })} required />
            <Field label="Name" value={nt.name} onChange={(e) => setNt({ ...nt, name: e.target.value })} required />
            <Select label="Inherits from (optional)" value={nt.parent} onChange={(e) => setNt({ ...nt, parent: e.target.value })}><option value="">None</option>{published.map((t) => <option key={t.slug} value={t.slug}>{t.name}</option>)}</Select>
            <label className="block"><span className="mb-1 block text-xs font-medium text-muted">Config (JSON)</span><textarea className="h-40 w-full rounded-md border border-line bg-surface p-2 font-mono text-xs" value={nt.config} onChange={(e) => setNt({ ...nt, config: e.target.value })} /></label>
            <p className="text-xs text-muted">Keys: business_models, applications, modules, custom_fields, terminology, roles, dashboards, recommended_plans, compliance, workflows.</p>
            <Btn type="submit" disabled={a.busy}>Create</Btn>
          </form>
        </Card>

        <Card title="Software editions (products)" className="xl:col-span-2">
          <Table head={["Product", "Versions", ""]} rows={(prods.data ?? []).map((p) => [<span key="n"><strong>{p.name}</strong> <code className="text-xs text-muted">{p.slug}</code></span>,
            <div key="v" className="flex flex-wrap gap-1">{p.versions.map((v) => <button key={v.version} onClick={() => pick(p, v)} className="rounded-full border border-line px-2 py-0.5 text-xs hover:bg-bg" aria-pressed={sel?.slug === p.slug && sel.version === v.version}>v{v.version} {v.status}</button>)}</div>,
            <Btn key="b" variant="ghost" onClick={() => newPv(p.slug)}>New version</Btn>])} empty="No products yet." />
          {sel && (
            <div className="mt-4 space-y-3 border-t border-line pt-4">
              <h3 className="text-sm font-semibold">{sel.slug} v{sel.version} {selVersion?.status === "published" && <Badge tone="ok">published — read only</Badge>}</h3>
              <fieldset disabled={selVersion?.status === "published"} className="space-y-3">
                <div className="grid max-h-48 gap-1 overflow-auto rounded-md border border-line p-2 sm:grid-cols-2">
                  {modules.map((m) => <label key={m} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={comp.modules.includes(m)} onChange={(e) => setComp({ ...comp, modules: e.target.checked ? [...comp.modules, m] : comp.modules.filter((x) => x !== m) })} /> {m}</label>)}
                  {!modules.length && <span className="text-sm text-muted">No application modules registered.</span>}
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Select label="Template" value={comp.template} onChange={(e) => setComp({ ...comp, template: e.target.value })}><option value="">None</option>{published.map((t) => <option key={t.slug} value={t.slug}>{t.name}</option>)}</Select>
                  <Field label="Recommended plans (slugs, comma-separated)" value={comp.plans} onChange={(e) => setComp({ ...comp, plans: e.target.value })} />
                  <Field label="Brand name" value={comp.name} onChange={(e) => setComp({ ...comp, name: e.target.value })} />
                  <Field label="Primary colour (#RRGGBB)" value={comp.color} onChange={(e) => setComp({ ...comp, color: e.target.value })} />
                </div>
              </fieldset>
              {selVersion?.status !== "published" && <div className="flex gap-2"><Btn onClick={saveComp} disabled={a.busy}>Save &amp; validate</Btn><Btn variant="ghost" onClick={test}>Test</Btn><Btn variant="ghost" onClick={publish}>Publish</Btn></div>}
              {checked && <div className="space-y-1 text-sm"><div><strong>Resolved modules:</strong> {checked.modules.join(", ") || "none"}</div>
                {checked.added_dependencies.length > 0 && <div className="text-muted">Added dependencies: {checked.added_dependencies.join(", ")}</div>}
                {checked.warnings.map((w) => <Alert key={w} kind="info">{w}</Alert>)}</div>}
            </div>
          )}
        </Card>
        <Card title="New product">
          <form onSubmit={createProduct} className="space-y-3">
            <Field label="Slug" value={np.slug} onChange={(e) => setNp({ ...np, slug: e.target.value })} required />
            <Field label="Name" value={np.name} onChange={(e) => setNp({ ...np, name: e.target.value })} required />
            <Field label="Description" value={np.description} onChange={(e) => setNp({ ...np, description: e.target.value })} />
            <Btn type="submit" disabled={a.busy}>Create</Btn>
          </form>
        </Card>
      </div>
    </>
  );
}
