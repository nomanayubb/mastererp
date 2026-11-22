"use client";
import { useParams } from "next/navigation";
import { Alert, Badge, Card, PageHeader, Table } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const tone = (s: string) => (s === "tested" || s === "released" ? "ok" : s === "implemented" ? "warn" : "neutral");

/** Module launcher: lists what the current user may do here, with the honest implementation status of each feature. */
export default function ModulePage() {
  const { app, module } = useParams<{ app: string; module: string }>();
  const { apps } = useAuth();
  const a = apps.find((x) => x.slug === app);
  const m = a?.modules.find((x) => x.slug === module);
  if (!a || !m) return <Alert>This module is not available to you. It may be inactive, not included in your plan, or outside your permissions.</Alert>;
  const unbuilt = m.features.every((f) => f.status === "specified");
  return (
    <>
      <PageHeader title={m.name} subtitle={`${a.name} — features you can use`} />
      {unbuilt && <div className="mb-4"><Alert kind="info">This module is registered and licensed for your workspace, but its screens are not built yet. The features below are specified and listed with their current status.</Alert></div>}
      <Card>
        <Table
          head={["Feature", "Your permissions", "Status"]}
          rows={m.features.map((f) => [<span key="n">{f.name}<code className="block text-xs text-muted">{f.key}</code></span>, f.actions.join(" · "), <Badge key="s" tone={tone(f.status)}>{f.status}</Badge>])}
        />
      </Card>
    </>
  );
}
