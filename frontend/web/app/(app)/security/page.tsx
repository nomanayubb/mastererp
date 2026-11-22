"use client";
import { useState, type FormEvent } from "react";
import { Alert, Btn, Card, Field, PageHeader, useAction } from "@/components/ui";
import { api } from "@/lib/api";

export default function Security() {
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [enabled, setEnabled] = useState(false);
  const a = useAction();

  async function start() {
    const r = await a.run(() => api<{ secret: string; otpauth_uri: string }>("/auth/mfa/enroll", { body: {} }));
    if (r) setEnroll(r);
  }
  async function confirm(e: FormEvent) {
    e.preventDefault();
    let ok = false;
    await a.run(async () => {
      await api("/auth/mfa/confirm", { body: { code } });
      ok = true;
    });
    if (ok) setEnabled(true);
  }

  return (
    <>
      <PageHeader title="Security" subtitle="Protect your account." />
      <Card title="Two-factor authentication" className="max-w-xl">
        {a.error && <Alert>{a.error}</Alert>}
        {enabled ? (
          <Alert kind="ok">Two-factor authentication is on. You’ll be asked for a code at sign-in.</Alert>
        ) : !enroll ? (
          <div className="space-y-3">
            <p className="text-sm text-muted">Use an authenticator app (Google Authenticator, 1Password, Authy…) for a second step at sign-in.</p>
            <Btn onClick={start} disabled={a.busy}>Set up</Btn>
          </div>
        ) : (
          <form onSubmit={confirm} className="space-y-3">
            <p className="text-sm">Add this key to your authenticator app, then enter the 6-digit code it shows.</p>
            <code className="block break-all rounded-md border border-line bg-bg p-2 text-sm">{enroll.secret}</code>
            <a className="text-xs text-brand underline" href={enroll.otpauth_uri}>Open in authenticator app</a>
            <Field label="Code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="one-time-code" />
            <Btn type="submit" disabled={a.busy}>Confirm</Btn>
          </form>
        )}
      </Card>
    </>
  );
}
