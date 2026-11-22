"use client";
import { useState, type FormEvent } from "react";
import { Alert, Btn, Card, Field, PageHeader, Select, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Company = { id: string; name: string; legal_name?: string | null; country?: string | null; base_currency: string };
type Branch = { id: string; company_id: string; name: string };
type Dept = { id: string; company_id: string; branch_id: string | null; parent_id: string | null; name: string };

export default function Organization() {
  const { can } = useAuth();
  const companies = useLoad(() => api<Company[]>("/organizations/companies"));
  const branches = useLoad(() => api<Branch[]>("/organizations/branches"));
  const depts = useLoad(() => api<Dept[]>("/organizations/departments"));
  const reloadAll = () => [companies, branches, depts].forEach((x) => x.reload());
  const cName = (id: string) => companies.data?.find((c) => c.id === id)?.name ?? id.slice(0, 8);
  const bName = (id: string | null) => (id ? branches.data?.find((b) => b.id === id)?.name ?? id.slice(0, 8) : "—");

  const [co, setCo] = useState({ name: "", legal_name: "", country: "", base_currency: "USD" });
  const [br, setBr] = useState({ company_id: "", name: "" });
  const [dp, setDp] = useState({ company_id: "", branch_id: "", parent_id: "", name: "" });
  const a1 = useAction(), a2 = useAction(), a3 = useAction();

  const addCompany = async (e: FormEvent) => {
    e.preventDefault();
    const r = await a1.run(() => api("/organizations/companies", { body: { ...co, legal_name: co.legal_name || null, country: co.country || null } }), "Company created");
    if (r) { setCo({ name: "", legal_name: "", country: "", base_currency: "USD" }); reloadAll(); }
  };
  const addBranch = async (e: FormEvent) => {
    e.preventDefault();
    const r = await a2.run(() => api("/organizations/branches", { body: br }), "Branch created");
    if (r) { setBr({ ...br, name: "" }); reloadAll(); }
  };
  const addDept = async (e: FormEvent) => {
    e.preventDefault();
    const r = await a3.run(() => api("/organizations/departments", { body: { company_id: dp.company_id, name: dp.name, branch_id: dp.branch_id || null, parent_id: dp.parent_id || null } }), "Department created");
    if (r) { setDp({ ...dp, name: "", parent_id: "" }); reloadAll(); }
  };

  return (
    <>
      <PageHeader title="Organization" subtitle="Companies, branches and departments. You only see what your access scope allows." />
      {companies.error && <Alert>{companies.error}</Alert>}
      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Companies">
          <Table head={["Name", "Country", "Currency"]} rows={(companies.data ?? []).map((c) => [<span key={c.id}>{c.name}{c.legal_name ? <span className="block text-xs text-muted">{c.legal_name}</span> : null}</span>, c.country ?? "—", c.base_currency])} />
          {can("platform.org.companies", "create") && (
            <form onSubmit={addCompany} className="mt-4 space-y-3 border-t border-line pt-4">
              {a1.error && <Alert>{a1.error}</Alert>}{a1.done && <Alert kind="ok">{a1.done}</Alert>}
              <Field label="Name" value={co.name} onChange={(e) => setCo({ ...co, name: e.target.value })} required />
              <Field label="Legal name" value={co.legal_name} onChange={(e) => setCo({ ...co, legal_name: e.target.value })} />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Country (ISO-2)" maxLength={2} value={co.country} onChange={(e) => setCo({ ...co, country: e.target.value.toUpperCase() })} />
                <Field label="Currency" maxLength={3} value={co.base_currency} onChange={(e) => setCo({ ...co, base_currency: e.target.value.toUpperCase() })} />
              </div>
              <Btn type="submit" disabled={a1.busy}>Add company</Btn>
            </form>
          )}
        </Card>

        <Card title="Branches">
          <Table head={["Name", "Company"]} rows={(branches.data ?? []).map((b) => [b.name, cName(b.company_id)])} />
          {can("platform.org.branches", "create") && (
            <form onSubmit={addBranch} className="mt-4 space-y-3 border-t border-line pt-4">
              {a2.error && <Alert>{a2.error}</Alert>}{a2.done && <Alert kind="ok">{a2.done}</Alert>}
              <Select label="Company" value={br.company_id} onChange={(e) => setBr({ ...br, company_id: e.target.value })} required>
                <option value="">Select…</option>
                {companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
              <Field label="Branch name" value={br.name} onChange={(e) => setBr({ ...br, name: e.target.value })} required />
              <Btn type="submit" disabled={a2.busy}>Add branch</Btn>
            </form>
          )}
        </Card>

        <Card title="Departments">
          <Table head={["Name", "Company", "Branch"]} rows={(depts.data ?? []).map((d) => [d.name, cName(d.company_id), bName(d.branch_id)])} />
          {can("platform.org.departments", "create") && (
            <form onSubmit={addDept} className="mt-4 space-y-3 border-t border-line pt-4">
              {a3.error && <Alert>{a3.error}</Alert>}{a3.done && <Alert kind="ok">{a3.done}</Alert>}
              <Select label="Company" value={dp.company_id} onChange={(e) => setDp({ ...dp, company_id: e.target.value, branch_id: "", parent_id: "" })} required>
                <option value="">Select…</option>
                {companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
              <Select label="Branch (optional)" value={dp.branch_id} onChange={(e) => setDp({ ...dp, branch_id: e.target.value })}>
                <option value="">None</option>
                {branches.data?.filter((b) => b.company_id === dp.company_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
              <Select label="Parent department (optional)" value={dp.parent_id} onChange={(e) => setDp({ ...dp, parent_id: e.target.value })}>
                <option value="">None</option>
                {depts.data?.filter((d) => d.company_id === dp.company_id).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
              <Field label="Department name" value={dp.name} onChange={(e) => setDp({ ...dp, name: e.target.value })} required />
              <Btn type="submit" disabled={a3.busy}>Add department</Btn>
            </form>
          )}
        </Card>
      </div>
    </>
  );
}
