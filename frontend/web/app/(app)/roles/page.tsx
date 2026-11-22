"use client";
import { useMemo, useState, type FormEvent } from "react";
import { Alert, Badge, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Perm = { feature_key: string; action: string; constraints: Record<string, unknown> };
type Role = { id: string; name: string; description: string; is_system: boolean; permissions: Perm[] };
type Assignment = { id: string; membership_id: string; role: string; scope: Record<string, string[]>; expires_at: string | null; email: string };
type Member = { id: string; email: string; status: string };
type Company = { id: string; name: string };
type App = { slug: string; modules: { features: { key: string; name: string; actions: string[] }[] }[] };

const summarize = (c: Record<string, unknown>) =>
  Object.entries(c).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(", ");

export default function Roles() {
  const { can } = useAuth();
  const roles = useLoad(() => api<Role[]>("/authz/roles"));
  const assigns = useLoad(() => api<Assignment[]>("/authz/assignments"));
  const members = useLoad(() => api<Member[]>("/users"));
  const companies = useLoad(() => api<Company[]>("/organizations/companies"));
  const catalog = useLoad(() => api<App[]>("/registry/catalog"));

  const features = useMemo(() => catalog.data?.flatMap((a) => a.modules.flatMap((m) => m.features)) ?? [], [catalog.data]);
  const [name, setName] = useState("");
  const [perms, setPerms] = useState<Perm[]>([]);
  const [pf, setPf] = useState({ feature_key: "", action: "", max_amount: "", no_self_approval: false, hide_fields: "" });
  const createA = useAction(), assignA = useAction(), delA = useAction();
  const [as, setAs] = useState({ membership_id: "", role_id: "", company_id: "", expires_at: "" });

  const selFeature = features.find((f) => f.key === pf.feature_key);

  function addPerm() {
    if (!pf.feature_key || !pf.action) return;
    const constraints: Record<string, unknown> = {};
    if (pf.max_amount) constraints.max_amount = Number(pf.max_amount);
    if (pf.no_self_approval) constraints.no_self_approval = true;
    if (pf.hide_fields.trim()) constraints.hide_fields = pf.hide_fields.split(",").map((s) => s.trim()).filter(Boolean);
    setPerms([...perms.filter((p) => !(p.feature_key === pf.feature_key && p.action === pf.action)), { feature_key: pf.feature_key, action: pf.action, constraints }]);
    setPf({ feature_key: "", action: "", max_amount: "", no_self_approval: false, hide_fields: "" });
  }

  async function createRole(e: FormEvent) {
    e.preventDefault();
    const r = await createA.run(() => api("/authz/roles", { body: { name, permissions: perms } }), "Role created");
    if (r) { setName(""); setPerms([]); roles.reload(); }
  }
  async function assign(e: FormEvent) {
    e.preventDefault();
    const body = {
      membership_id: as.membership_id, role_id: as.role_id,
      scope: as.company_id ? { company_ids: [as.company_id] } : {},
      expires_at: as.expires_at ? new Date(as.expires_at).toISOString() : null,
    };
    const r = await assignA.run(() => api("/authz/assignments", { body }), "Role assigned");
    if (r) { assigns.reload(); }
  }

  return (
    <>
      <PageHeader title="Roles & access" subtitle="Who can do what. Enforced by the server on every request." />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Roles">
          {roles.error && <Alert>{roles.error}</Alert>}
          <div className="space-y-4">
            {roles.data?.map((r) => (
              <div key={r.id} className="rounded-md border border-line p-3">
                <div className="flex items-center justify-between">
                  <strong className="text-sm">{r.name}</strong>
                  <div className="flex items-center gap-2">
                    {r.is_system && <Badge>system</Badge>}
                    {!r.is_system && can("platform.authz.roles", "delete") && (
                      <Btn variant="danger" disabled={delA.busy} onClick={async () => { if (confirm(`Delete role “${r.name}”? Assignments are removed too.`)) { await delA.run(() => api(`/authz/roles/${r.id}`, { method: "DELETE" })); roles.reload(); assigns.reload(); } }}>Delete</Btn>
                    )}
                  </div>
                </div>
                <ul className="mt-2 space-y-1 text-xs text-muted">
                  {r.permissions.map((p, i) => (
                    <li key={i}><code>{p.feature_key}</code> : <strong>{p.action}</strong>{Object.keys(p.constraints).length ? ` (${summarize(p.constraints)})` : ""}</li>
                  ))}
                  {!r.permissions.length && <li>No permissions.</li>}
                </ul>
              </div>
            ))}
          </div>
          {delA.error && <div className="mt-3"><Alert>{delA.error}</Alert></div>}
        </Card>

        <div className="space-y-6">
          {can("platform.authz.roles", "create") && (
            <Card title="Create a role">
              <form onSubmit={createRole} className="space-y-3">
                {createA.error && <Alert>{createA.error}</Alert>}{createA.done && <Alert kind="ok">{createA.done}</Alert>}
                <Field label="Role name" value={name} onChange={(e) => setName(e.target.value)} required />
                <fieldset className="space-y-3 rounded-md border border-line p-3">
                  <legend className="px-1 text-xs text-muted">Add a permission</legend>
                  <Select label="Feature" value={pf.feature_key} onChange={(e) => setPf({ ...pf, feature_key: e.target.value, action: "" })}>
                    <option value="">Select…</option>
                    {features.map((f) => <option key={f.key} value={f.key}>{f.name} — {f.key}</option>)}
                  </Select>
                  <Select label="Action" value={pf.action} onChange={(e) => setPf({ ...pf, action: e.target.value })} disabled={!selFeature}>
                    <option value="">Select…</option>
                    {selFeature?.actions.map((a) => <option key={a} value={a}>{a}</option>)}
                  </Select>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Max amount (optional)" type="number" min={0} value={pf.max_amount} onChange={(e) => setPf({ ...pf, max_amount: e.target.value })} />
                    <Field label="Hide fields (comma-separated)" value={pf.hide_fields} onChange={(e) => setPf({ ...pf, hide_fields: e.target.value })} />
                  </div>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={pf.no_self_approval} onChange={(e) => setPf({ ...pf, no_self_approval: e.target.checked })} /> Cannot act on own records (no self-approval)</label>
                  <Btn type="button" variant="ghost" onClick={addPerm} disabled={!pf.feature_key || !pf.action}>Add permission</Btn>
                </fieldset>
                {perms.length > 0 && (
                  <ul className="space-y-1 text-xs">
                    {perms.map((p, i) => (
                      <li key={i} className="flex items-center justify-between">
                        <span><code>{p.feature_key}</code> : <strong>{p.action}</strong> {Object.keys(p.constraints).length ? `(${summarize(p.constraints)})` : ""}</span>
                        <button type="button" className="text-danger underline" onClick={() => setPerms(perms.filter((_, j) => j !== i))}>remove</button>
                      </li>
                    ))}
                  </ul>
                )}
                <Btn type="submit" disabled={createA.busy}>Create role</Btn>
              </form>
            </Card>
          )}

          <Card title="Assignments">
            {assigns.error && <Alert>{assigns.error}</Alert>}
            <Table
              head={["Person", "Role", "Scope", "Expires", ""]}
              rows={(assigns.data ?? []).map((a) => [
                a.email, a.role,
                a.scope.company_ids?.length ? a.scope.company_ids.map((id) => companies.data?.find((c) => c.id === id)?.name ?? id.slice(0, 8)).join(", ") : "All",
                a.expires_at ? new Date(a.expires_at).toLocaleString() : "Never",
                can("platform.authz.assignments", "delete") ? (
                  <Btn key="d" variant="danger" disabled={delA.busy} onClick={async () => { await delA.run(() => api(`/authz/assignments/${a.id}`, { method: "DELETE" })); assigns.reload(); }}>Remove</Btn>
                ) : null,
              ])}
            />
            {can("platform.authz.assignments", "create") && (
              <form onSubmit={assign} className="mt-4 space-y-3 border-t border-line pt-4">
                {assignA.error && <Alert>{assignA.error}</Alert>}{assignA.done && <Alert kind="ok">{assignA.done}</Alert>}
                <div className="grid gap-3 sm:grid-cols-2">
                  <Select label="Person" value={as.membership_id} onChange={(e) => setAs({ ...as, membership_id: e.target.value })} required>
                    <option value="">Select…</option>
                    {members.data?.filter((m) => m.status === "active").map((m) => <option key={m.id} value={m.id}>{m.email}</option>)}
                  </Select>
                  <Select label="Role" value={as.role_id} onChange={(e) => setAs({ ...as, role_id: e.target.value })} required>
                    <option value="">Select…</option>
                    {roles.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </Select>
                  <Select label="Limit to company (optional)" value={as.company_id} onChange={(e) => setAs({ ...as, company_id: e.target.value })}>
                    <option value="">All companies</option>
                    {companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </Select>
                  <Field label="Expires (optional)" type="datetime-local" value={as.expires_at} onChange={(e) => setAs({ ...as, expires_at: e.target.value })} />
                </div>
                <p className="text-xs text-muted">Note: every invited member also holds the base Member role (read-only organization view). Remove it above to make a scope limit effective.</p>
                <Btn type="submit" disabled={assignA.busy}>Assign role</Btn>
              </form>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
