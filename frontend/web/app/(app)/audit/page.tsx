"use client";
import { useState } from "react";
import { Alert, Badge, Btn, Card, PageHeader, Table, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";

type Entry = { seq: number; ts: string; actor_user_id: string | null; action: string; entity_type: string | null; data: Record<string, unknown> };
type Verify = { ok: boolean; count: number; first_bad_seq: number | null };

export default function Audit() {
  const log = useLoad(() => api<Entry[]>("/audit?limit=200"));
  const act = useAction();
  const [result, setResult] = useState<Verify | null>(null);

  async function verify() {
    const r = await act.run(() => api<Verify>("/audit/verify"));
    if (r) setResult(r);
  }

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Every change is recorded in a tamper-evident hash chain."
        actions={<Btn variant="ghost" onClick={verify} disabled={act.busy}>Verify integrity</Btn>}
      />
      {act.error && <Alert>{act.error}</Alert>}
      {result && (
        <div className="mb-4">
          {result.ok ? <Alert kind="ok">Chain intact — {result.count} entries verified.</Alert> : <Alert>Tampering detected at entry #{result.first_bad_seq}.</Alert>}
        </div>
      )}
      {log.error && <Alert>{log.error}</Alert>}
      <Card>
        <Table
          head={["#", "When", "Action", "Entity", "Details"]}
          rows={(log.data ?? []).map((e) => [
            e.seq,
            new Date(e.ts).toLocaleString(),
            <Badge key="a">{e.action}</Badge>,
            e.entity_type ?? "—",
            <code key="d" className="break-all text-xs text-muted">{JSON.stringify(e.data)}</code>,
          ])}
        />
      </Card>
    </>
  );
}
