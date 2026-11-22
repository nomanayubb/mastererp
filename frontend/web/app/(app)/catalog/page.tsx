"use client";
import { Alert, Badge, Card, PageHeader, useLoad } from "@/components/ui";
import { api } from "@/lib/api";

type Feature = { key: string; name: string; actions: string[]; status: string; submodule: string | null };
type App = { slug: string; name: string; category: string; version: string; modules: { slug: string; name: string; features: Feature[] }[] };

const tone = (s: string) => (s === "tested" || s === "released" ? "ok" : s === "implemented" ? "warn" : "neutral");

export default function Catalog() {
  const cat = useLoad(() => api<App[]>("/registry/catalog"));
  return (
    <>
      <PageHeader title="Applications" subtitle="Everything published on the platform. Applications beyond the core need to be enabled for your workspace." />
      {cat.error && <Alert>{cat.error}</Alert>}
      <div className="space-y-4">
        {cat.data?.map((a) => (
          <Card key={a.slug} title={`${a.name}`} actions={<><Badge>{a.category}</Badge><Badge>v{a.version}</Badge></>}>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {a.modules.map((m) => (
                <div key={m.slug}>
                  <h3 className="mb-2 text-sm font-semibold">{m.name}</h3>
                  <ul className="space-y-1.5">
                    {m.features.map((f) => (
                      <li key={f.key} className="flex items-start justify-between gap-2 text-sm">
                        <span>
                          {f.name}
                          <span className="block text-xs text-muted">{f.actions.join(" · ")}</span>
                        </span>
                        <Badge tone={tone(f.status)}>{f.status}</Badge>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
