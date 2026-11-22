"use client";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";

type App = { slug: string; name: string; category: string; version: string; status: string; origin: string; legacy_ref: string | null };
type Feature = { key: string; name: string; actions: string[]; status: string; origin: string; sensitive: boolean; legacy_ref: string | null };
type Industry = { slug: string; name: string; parent: string | null; status: string };

const S = { realm: "staff" as const };

export default function Registry() {
  const apps = useLoad(() => api<App[]>("/platform/registry/applications", S));
  const feats = useLoad(() => api<Feature[]>("/platform/registry/features", S));
  const inds = useLoad(() => api<Industry[]>("/platform/registry/industries", S));
  const [tab, setTab] = useState<"apps" | "features" | "industries">("apps");
  const [fa, setFa] = useState({ slug: "", name: "", category: "general" });
  const [ff, setFf] = useState({ application_slug: "", module_slug: "", slug: "", name: "", actions: "view,create" });
  const [fm, setFm] = useState({ application_slug: "", slug: "", name: "" });
  const [fi, setFi] = useState({ slug: "", name: "", parent_slug: "" });
  const a = useAction();

  async function post(path: string, body: unknown, reload: () => void, msg: string) {
    const r = await a.run(() => api(path, { ...S, body }), msg);
    if (r !== null) reload();
  }
  const publish = async (slug: string) => { await a.run(() => api(`/platform/registry/applications/${slug}`, { ...S, method: "PATCH", body: { status: "published" } })); apps.reload(); };
  const sync = async () => { const r = await a.run(() => api<Record<string, number>>("/platform/registry/sync", { ...S, body: {} })); if (r) { a.run(async () => r, `Synced: ${JSON.stringify(r)}`); apps.reload(); feats.reload(); } };

  return (
    <>
      <PageHeader title="Registry" subtitle="Applications, modules, features and industries available on the platform." actions={<Btn variant="ghost" onClick={sync}>Sync code manifests</Btn>} />
      {a.error && <div className="mb-3"><Alert>{a.error}</Alert></div>}
      {a.done && <div className="mb-3"><Alert kind="ok">{a.done}</Alert></div>}
      <div role="tablist" className="mb-4 flex gap-1">
        {(["apps", "features", "industries"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`rounded-md px-3 py-1.5 text-sm ${tab === t ? "bg-surface font-semibold text-brand border border-line" : "hover:bg-surface"}`}>
            {{ apps: "Applications", features: "Features", industries: "Industries" }[t]}
          </button>
        ))}
      </div>

      {tab === "apps" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title="Applications" className="lg:col-span-2">
            <Table head={["Name", "Slug", "Version", "Status", "Origin", ""]} rows={(apps.data ?? []).map((x) => [x.name, <code key="s">{x.slug}</code>, x.version, <Badge key="b" tone={x.status === "published" ? "ok" : "warn"}>{x.status}</Badge>, x.origin, x.status === "draft" ? <Btn key="p" variant="ghost" onClick={() => publish(x.slug)}>Publish</Btn> : null])} />
          </Card>
          <div className="space-y-6">
            <Card title="New application">
              <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); post("/platform/registry/applications", fa, apps.reload, "Application created (draft)"); }}>
                <Field label="Slug" value={fa.slug} onChange={(e) => setFa({ ...fa, slug: e.target.value })} required placeholder="farm_mgmt" />
                <Field label="Name" value={fa.name} onChange={(e) => setFa({ ...fa, name: e.target.value })} required />
                <Field label="Category" value={fa.category} onChange={(e) => setFa({ ...fa, category: e.target.value })} />
                <Btn type="submit" disabled={a.busy}>Create</Btn>
              </form>
            </Card>
            <Card title="New module">
              <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); post("/platform/registry/modules", fm, feats.reload, "Module created"); }}>
                <Select label="Application" value={fm.application_slug} onChange={(e) => setFm({ ...fm, application_slug: e.target.value })} required>
                  <option value="">Select…</option>{apps.data?.filter((x) => x.origin === "config").map((x) => <option key={x.slug} value={x.slug}>{x.name}</option>)}
                </Select>
                <Field label="Slug" value={fm.slug} onChange={(e) => setFm({ ...fm, slug: e.target.value })} required />
                <Field label="Name" value={fm.name} onChange={(e) => setFm({ ...fm, name: e.target.value })} required />
                <Btn type="submit" disabled={a.busy}>Create</Btn>
              </form>
            </Card>
          </div>
        </div>
      )}

      {tab === "features" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title={`Features (${feats.data?.length ?? 0})`} className="lg:col-span-2">
            <Table head={["Key", "Actions", "Status", "Spec #"]} rows={(feats.data ?? []).map((f) => [<code key="k">{f.key}</code>, f.actions.join(", "), <Badge key="s" tone={f.status === "tested" ? "ok" : f.status === "deprecated" ? "danger" : "neutral"}>{f.status}</Badge>, f.legacy_ref ?? "—"])} />
          </Card>
          <Card title="New feature (config-defined)">
            <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); post("/platform/registry/features", { ...ff, actions: ff.actions.split(",").map((s) => s.trim()).filter(Boolean) }, feats.reload, "Feature created"); }}>
              <Field label="Application slug" value={ff.application_slug} onChange={(e) => setFf({ ...ff, application_slug: e.target.value })} required />
              <Field label="Module slug" value={ff.module_slug} onChange={(e) => setFf({ ...ff, module_slug: e.target.value })} required />
              <Field label="Feature slug" value={ff.slug} onChange={(e) => setFf({ ...ff, slug: e.target.value })} required />
              <Field label="Name" value={ff.name} onChange={(e) => setFf({ ...ff, name: e.target.value })} required />
              <Field label="Actions (comma-separated)" value={ff.actions} onChange={(e) => setFf({ ...ff, actions: e.target.value })} required />
              <Btn type="submit" disabled={a.busy}>Create</Btn>
            </form>
          </Card>
        </div>
      )}

      {tab === "industries" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title="Industries" className="lg:col-span-2">
            <Table head={["Name", "Slug", "Parent", "Status"]} rows={(inds.data ?? []).map((i) => [i.name, <code key="s">{i.slug}</code>, i.parent ?? "—", i.status])} empty="No industries registered yet." />
          </Card>
          <Card title="New industry">
            <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); post("/platform/registry/industries", { ...fi, parent_slug: fi.parent_slug || null }, inds.reload, "Industry created"); }}>
              <Field label="Slug" value={fi.slug} onChange={(e) => setFi({ ...fi, slug: e.target.value })} required />
              <Field label="Name" value={fi.name} onChange={(e) => setFi({ ...fi, name: e.target.value })} required />
              <Select label="Parent (optional)" value={fi.parent_slug} onChange={(e) => setFi({ ...fi, parent_slug: e.target.value })}>
                <option value="">None</option>{inds.data?.map((i) => <option key={i.slug} value={i.slug}>{i.name}</option>)}
              </Select>
              <Btn type="submit" disabled={a.busy}>Create</Btn>
            </form>
          </Card>
        </div>
      )}
    </>
  );
}
