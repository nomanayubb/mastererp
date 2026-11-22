"use client";
import Link from "next/link";
import { Badge, Card, PageHeader, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Co = { id: string };
type Member = { id: string };
type App = { slug: string };
type Dash = { name: string | null; widgets: { title: string; source: string; value: number }[] };

export default function Dashboard() {
  const { tenant, me, can, term } = useAuth();
  const dash = useLoad(() => api<Dash>("/config/dashboard"));
  const co = useLoad(() => (can("platform.org.companies", "view") ? api<Co[]>("/organizations/companies") : Promise.resolve([])), []);
  const mem = useLoad(() => (can("platform.users.members", "view") ? api<Member[]>("/users") : Promise.resolve([])), []);
  const cat = useLoad(() => (can("platform.registry.catalog", "view") ? api<App[]>("/registry/catalog") : Promise.resolve([])), []);
  const roles = [...new Set(me?.permissions.map((p) => p.role))];
  const configured = (dash.data?.widgets.length ?? 0) > 0;

  const stat = (label: string, value: number | string, href?: string) => (
    <Card key={label}>
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {href && <Link href={href} className="mt-2 inline-block text-xs text-brand underline">Open</Link>}
    </Card>
  );
  const hrefFor = (s: string) => (s === "members" ? "/members" : "/organization");

  return (
    <>
      <PageHeader title={`Welcome${tenant ? `, ${tenant.name}` : ""}`} subtitle={configured ? `${dash.data?.name} — your workspace at a glance.` : "Your workspace at a glance."} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {configured ? dash.data!.widgets.map((w) => stat(w.title, w.value, hrefFor(w.source))) : (
          <>
            {stat(term("companies", "Companies"), co.data?.length ?? "—", "/organization")}
            {stat(term("members", "Members"), mem.data?.length ?? "—", "/members")}
            {stat("Applications available", cat.data?.length ?? "—", "/catalog")}
          </>
        )}
        <Card>
          <div className="text-xs text-muted">Your roles</div>
          <div className="mt-2 flex flex-wrap gap-1">{roles.map((r) => <Badge key={r}>{r}</Badge>)}</div>
        </Card>
      </div>
      <Card title="Getting started" className="mt-6">
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          <li>Pick an industry template or edition under <Link href="/configuration" className="text-brand underline">Configuration</Link>.</li>
          <li>Create your <Link href="/organization" className="text-brand underline">{term("companies", "companies").toLowerCase()}, {term("branches", "branches").toLowerCase()} and {term("departments", "departments").toLowerCase()}</Link>.</li>
          <li>Invite teammates under <Link href="/members" className="text-brand underline">Members</Link> and set what they can do under <Link href="/roles" className="text-brand underline">Roles &amp; access</Link>.</li>
          <li>Turn on <Link href="/security" className="text-brand underline">two-factor authentication</Link> for your account.</li>
        </ol>
      </Card>
    </>
  );
}
