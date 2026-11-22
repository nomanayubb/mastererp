"use client";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Mod = { key: string; name: string; features: number; active: boolean; entitled: boolean; depends_on_modules: string[] };
type AppCat = { slug: string; name: string; modules: Mod[] };
type Tpl = { slug: string; name: string; version: number; industry: string };
type Resolved = { chain: string[]; config: Record<string, unknown>; overrides: { path: string; from: string; by: string }[] };
type Product = { slug: string; name: string; description: string; versions: { version: number; composition: { modules?: string[]; template?: string } }[] };
type FieldDef = { entity: string; key: string; label: string; type: string; required: boolean; options: string[]; source: string };
type Result = Record<string, unknown>;

const TABS = ["Modules", "Industry templates", "Software editions", "Custom fields", "Terminology"] as const;
const TERMS = [["companies", "Companies"], ["branches", "Branches"], ["departments", "Departments"], ["members", "Members"]] as const;

export default function Configuration() {
  const { can, terms, reloadConfig } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Modules");
  const mods = useLoad(() => api<AppCat[]>("/config/modules"));
  const tpls = useLoad(() => (can("platform.config.templates", "view") ? api<Tpl[]>("/config/templates") : Promise.resolve([])));
  const prods = useLoad(() => (can("platform.config.products", "view") ? api<Product[]>("/config/products") : Promise.resolve([])));
  const fields = useLoad(() => (can("platform.config.fields", "view") ? api<FieldDef[]>("/config/fields") : Promise.resolve([])));
  const a = useAction();
  const [preview, setPreview] = useState<Resolved | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [nf, setNf] = useState({ key: "", label: "", type: "text", required: false, options: "" });
  const [term, setTerm] = useState({ term: "companies", label: "" });
  const edit = can("platform.config.modules", "edit");

  const done = async (r: unknown, reload: (() => void)[] = []) => { if (r !== undefined) { await reloadConfig(); reload.forEach((x) => x()); } };
  const toggle = async (m: Mod) => {
    const r = await a.run(() => m.active
      ? api("/config/modules/deactivate", { body: { module: m.key } })
      : api<Result>("/config/modules/activate", { body: { modules: [m.key], with_dependencies: true } }), m.active ? `${m.name} deactivated` : `${m.name} activated`);
    await reloadConfig(); mods.reload(); void r;
  };

  return (
    <>
      <PageHeader title="Configuration" subtitle="Turn modules on, apply an industry template or software edition, and adapt fields and wording to your organization." />
      {a.error && <div className="mb-3"><Alert>{a.error}</Alert></div>}
      {a.done && <div className="mb-3"><Alert kind="ok">{a.done}</Alert></div>}
      <div role="tablist" className="mb-4 flex flex-wrap gap-1">
        {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`rounded-md px-3 py-1.5 text-sm ${tab === t ? "border border-line bg-surface font-semibold text-brand" : "hover:bg-surface"}`}>{t}</button>)}
      </div>

      {tab === "Modules" && (
        <div className="space-y-4">
          {mods.error && <Alert>{mods.error}</Alert>}
          {mods.data?.map((app) => (
            <Card key={app.slug} title={app.name}>
              <Table
                head={["Module", "Features", "Needs", "Licence", "Status", ""]}
                rows={app.modules.map((m) => [
                  m.name, m.features, m.depends_on_modules.length ? m.depends_on_modules.join(", ") : "—",
                  <Badge key="l" tone={m.entitled ? "ok" : "warn"}>{m.entitled ? "included" : "not in plan"}</Badge>,
                  <Badge key="s" tone={m.active ? "ok" : "neutral"}>{m.active ? "active" : "off"}</Badge>,
                  edit ? <Btn key="b" variant={m.active ? "danger" : "ghost"} disabled={a.busy} onClick={() => toggle(m)}>{m.active ? "Deactivate" : "Activate"}</Btn> : null,
                ])}
              />
            </Card>
          ))}
          {!mods.data?.length && !mods.loading && <p className="text-sm text-muted">No applications are published yet.</p>}
          <p className="text-xs text-muted">Activating a module also turns on the modules it depends on. A module can only be deactivated when no active module needs it. Modules not in your plan stay hidden from navigation until they are licensed.</p>
        </div>
      )}

      {tab === "Industry templates" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Published templates">
            <Table head={["Template", "Industry", ""]} rows={(tpls.data ?? []).map((t) => [<span key="n">{t.name} <code className="text-xs text-muted">v{t.version}</code></span>, t.industry,
              <div key="b" className="flex gap-2">
                <Btn variant="ghost" onClick={async () => { const r = await a.run(() => api<Resolved>(`/config/templates/${t.slug}/preview`)); if (r) { setPreview(r); setResult(null); } }}>Preview</Btn>
                {can("platform.config.templates", "apply") && <Btn disabled={a.busy} onClick={async () => { if (!confirm(`Apply “${t.name}”? Existing settings you already changed are kept.`)) return; const r = await a.run(() => api<Result>(`/config/templates/${t.slug}/apply`, { body: {} }), `${t.name} applied`); if (r) { setResult(r); setPreview(null); await done(r, [mods.reload, fields.reload]); } }}>Apply</Btn>}
              </div>])} empty="No templates published yet." />
          </Card>
          <Card title={preview ? `Preview — inherits ${preview.chain.join(" → ")}` : result ? "Result" : "Details"}>
            {preview && (<div className="space-y-3 text-sm">
              <pre className="max-h-72 overflow-auto rounded-md border border-line bg-bg p-2 text-xs">{JSON.stringify(preview.config, null, 2)}</pre>
              {preview.overrides.length > 0 && <div><strong>Overrides</strong><ul className="mt-1 text-xs text-muted">{preview.overrides.map((o, i) => <li key={i}><code>{o.path}</code>: {o.from} → {o.by}</li>)}</ul></div>}
            </div>)}
            {result && <ResultView r={result} />}
            {!preview && !result && <p className="text-sm text-muted">Preview a template to see exactly what it would set up, and where each setting comes from.</p>}
          </Card>
        </div>
      )}

      {tab === "Software editions" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Available editions">
            <Table head={["Edition", "Modules", ""]} rows={(prods.data ?? []).map((p) => {
              const v = p.versions[0];
              return [<span key="n">{p.name}<span className="block text-xs text-muted">{p.description}</span></span>, <span key="m" className="text-xs">{v?.composition.modules?.join(", ") ?? "—"}</span>,
                can("platform.config.products", "install") ? <Btn key="b" disabled={a.busy} onClick={async () => { if (!confirm(`Install “${p.name}”? It activates its modules, applies its template and branding.`)) return; const r = await a.run(() => api<Result>(`/config/products/${p.slug}/install`, { body: {} }), `${p.name} installed`); if (r) { setResult(r); await done(r, [mods.reload, fields.reload]); } }}>Install</Btn> : null];
            })} empty="No editions published yet." />
          </Card>
          <Card title="Result">{result ? <ResultView r={result} /> : <p className="text-sm text-muted">Installing an edition shows what was set up.</p>}</Card>
        </div>
      )}

      {tab === "Custom fields" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title="Company fields" className="lg:col-span-2">
            <Table head={["Label", "Key", "Type", "Required", "Source", ""]} rows={(fields.data ?? []).map((f) => [f.label, <code key="k">{f.key}</code>, f.type + (f.options.length ? ` (${f.options.join("/")})` : ""), f.required ? "yes" : "no", f.source,
              can("platform.config.fields", "delete") ? <Btn key="d" variant="danger" onClick={async () => { await a.run(() => api(`/config/fields/${f.entity}/${f.key}`, { method: "DELETE" })); fields.reload(); }}>Delete</Btn> : null])} empty="No custom fields yet." />
          </Card>
          {can("platform.config.fields", "create") && (
            <Card title="Add a field">
              <form className="space-y-3" onSubmit={async (e: FormEvent) => { e.preventDefault(); const r = await a.run(async () => { await api("/config/fields", { body: { entity: "platform.company", key: nf.key, label: nf.label, type: nf.type, required: nf.required, options: nf.options.split(",").map((s) => s.trim()).filter(Boolean) } }); return true; }, "Field added"); if (r) { setNf({ key: "", label: "", type: "text", required: false, options: "" }); fields.reload(); } }}>
                <Field label="Label" value={nf.label} onChange={(e) => setNf({ ...nf, label: e.target.value, key: nf.key || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") })} required />
                <Field label="Key" hint="Lowercase letters, digits, underscore." value={nf.key} onChange={(e) => setNf({ ...nf, key: e.target.value })} required />
                <Select label="Type" value={nf.type} onChange={(e) => setNf({ ...nf, type: e.target.value })}>{["text", "number", "date", "boolean", "select"].map((t) => <option key={t}>{t}</option>)}</Select>
                {nf.type === "select" && <Field label="Options (comma-separated)" value={nf.options} onChange={(e) => setNf({ ...nf, options: e.target.value })} required />}
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={nf.required} onChange={(e) => setNf({ ...nf, required: e.target.checked })} /> Required</label>
                <Btn type="submit" disabled={a.busy}>Add field</Btn>
              </form>
            </Card>
          )}
        </div>
      )}

      {tab === "Terminology" && (
        <Card title="Your wording" className="max-w-xl">
          <p className="mb-3 text-sm text-muted">Rename things to match how your organization talks, e.g. “Companies” → “Stores”.</p>
          <ul className="mb-4 space-y-1 text-sm">{TERMS.map(([k, d]) => <li key={k}><code>{k}</code>: {terms[k] ?? <span className="text-muted">{d} (default)</span>}</li>)}</ul>
          {can("platform.config.terminology", "edit") && (
            <form className="flex items-end gap-3" onSubmit={async (e: FormEvent) => { e.preventDefault(); await a.run(() => api("/config/terminology", { method: "PUT", body: term }), "Saved"); await reloadConfig(); setTerm({ ...term, label: "" }); }}>
              <Select label="Term" value={term.term} onChange={(e) => setTerm({ ...term, term: e.target.value })}>{TERMS.map(([k]) => <option key={k}>{k}</option>)}</Select>
              <div className="flex-1"><Field label="Label" value={term.label} onChange={(e) => setTerm({ ...term, label: e.target.value })} required /></div>
              <Btn type="submit" disabled={a.busy}>Save</Btn>
            </form>
          )}
        </Card>
      )}
    </>
  );
}

function ResultView({ r }: { r: Result }) {
  const list = (v: unknown) => (Array.isArray(v) ? (v as string[]) : []);
  const created = (r.created ?? {}) as Record<string, string[]>;
  const skipped = (r.skipped_existing ?? {}) as Record<string, string[]>;
  return (
    <div className="space-y-2 text-sm">
      <div><strong>Modules activated:</strong> {list(r.activated_modules).join(", ") || "none new"}</div>
      {list(r.added_dependencies).length > 0 && <div className="text-muted">Added as dependencies: {list(r.added_dependencies).join(", ")}</div>}
      {list(r.not_entitled).length > 0 && <Alert kind="info">Not in your plan yet (hidden until licensed): {list(r.not_entitled).join(", ")}</Alert>}
      {Object.entries(created).map(([k, v]) => v.length > 0 && <div key={k}><strong>Created {k}:</strong> {v.join(", ")}</div>)}
      {Object.entries(skipped).map(([k, v]) => v.length > 0 && <div key={k} className="text-muted">Kept your existing {k}: {v.join(", ")}</div>)}
      {list(r.recommended_plans).length > 0 && <div className="text-muted">Recommended plans: {list(r.recommended_plans).join(", ")}</div>}
    </div>
  );
}
