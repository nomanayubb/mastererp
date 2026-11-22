"use client";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Member = { id: string; email: string; display_name: string; role: string; status: string };

export default function Members() {
  const { can } = useAuth();
  const members = useLoad(() => api<Member[]>("/users"));
  const [inv, setInv] = useState({ email: "", role: "member" });
  const [issued, setIssued] = useState<{ token: string; email: string } | null>(null);
  const a = useAction(), d = useAction();

  async function invite(e: FormEvent) {
    e.preventDefault();
    const r = await a.run(() => api<{ token: string; email: string }>("/users/invitations", { body: inv }));
    if (r) { setIssued(r); setInv({ email: "", role: "member" }); }
  }

  return (
    <>
      <PageHeader title="Members" subtitle="People with access to this workspace." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Members" className="lg:col-span-2">
          {members.error && <Alert>{members.error}</Alert>}
          {d.error && <Alert>{d.error}</Alert>}
          <Table
            head={["Email", "Name", "Base role", "Status", ""]}
            rows={(members.data ?? []).map((m) => [
              m.email, m.display_name || "—", m.role,
              <Badge key="s" tone={m.status === "active" ? "ok" : "danger"}>{m.status}</Badge>,
              can("platform.users.members", "edit") && m.role !== "owner" && m.status === "active" ? (
                <Btn key="b" variant="danger" disabled={d.busy} onClick={async () => { if (confirm(`Disable ${m.email}? Their sessions end immediately.`)) { await d.run(() => api(`/users/${m.id}/disable`, { method: "POST", body: {} })); members.reload(); } }}>Disable</Btn>
              ) : null,
            ])}
          />
        </Card>
        {can("platform.users.invitations", "create") && (
          <Card title="Invite someone">
            <form onSubmit={invite} className="space-y-3">
              {a.error && <Alert>{a.error}</Alert>}
              <Field label="Email" type="email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} required />
              <Select label="Base role" value={inv.role} onChange={(e) => setInv({ ...inv, role: e.target.value })}>
                <option value="member">Member (read-only)</option>
                <option value="admin">Admin</option>
              </Select>
              <Btn type="submit" disabled={a.busy}>Create invitation</Btn>
            </form>
            {issued && (
              <div className="mt-4 space-y-2">
                <Alert kind="info">Email delivery isn’t set up yet. Share this link with {issued.email}:</Alert>
                <code className="block break-all rounded-md border border-line bg-bg p-2 text-xs">{typeof window !== "undefined" ? window.location.origin : ""}/accept?token={issued.token}</code>
              </div>
            )}
          </Card>
        )}
      </div>
    </>
  );
}
