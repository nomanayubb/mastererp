"use client";
import Link from "next/link";
import { Badge, Card, PageHeader, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Co = { id: string };
type Member = { id: string };
type App = { slug: string; name: string; modules: { features: { status: string }[] }[] };

export default function Dashboard() {
  const { tenant, me, can } = useAuth();
  const co = useLoad(() => (can("platform.org.companies", "view") ? api<Co[]>("/organizations/companies") : Promise.resolve([])), []);
  const mem = useLoad(() => (can("platform.users.members", "view") ? api<Member[]>("/users") : Promise.resolve([])), []);
  const cat = useLoad(() => (can("platform.registry.catalog", "view") ? api<App[]>("/registry/catalog") : Promise.resolve([])), []);
  const roles = [...new Set(me?.permissions.map((p) => p.role))];

  const stat = (label: string, value: number | string, href?: string) => (
    <Card>
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {href && (
        <Link href={href} className="mt-2 inline-block text-xs text-brand underline">
          Open
        </Link>
      )}
    </Card>
  );

  return (
    <>
      <PageHeader title={`Welcome${tenant ? `, ${tenant.name}` : ""}`} subtitle="Your workspace at a glance." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stat("Companies", co.data?.length ?? "—", "/organization")}
        {stat("Members", mem.data?.length ?? "—", "/members")}
        {stat("Applications available", cat.data?.length ?? "—", "/catalog")}
        <Card>
          <div className="text-xs text-muted">Your roles</div>
          <div className="mt-2 flex flex-wrap gap-1">{roles.map((r) => <Badge key={r}>{r}</Badge>)}</div>
        </Card>
      </div>
      <Card title="Getting started" className="mt-6">
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          <li>Create your <Link href="/organization" className="text-brand underline">company, branches and departments</Link>.</li>
          <li>Invite teammates under <Link href="/members" className="text-brand underline">Members</Link>.</li>
          <li>Define what each person can do under <Link href="/roles" className="text-brand underline">Roles &amp; access</Link>.</li>
          <li>Turn on <Link href="/security" className="text-brand underline">two-factor authentication</Link> for your account.</li>
        </ol>
      </Card>
    </>
  );
}
