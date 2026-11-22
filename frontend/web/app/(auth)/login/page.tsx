"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert, Btn, Card, Field, useAction } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function Login() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [f, setF] = useState({ tenant_slug: "", email: "", password: "", mfa_code: "" });
  const [needMfa, setNeedMfa] = useState(false);
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await act.run(async () => {
      try {
        return await api<{ access_token: string; refresh_token: string }>("/auth/login", {
          body: { ...f, mfa_code: f.mfa_code || undefined },
          auth: false,
        });
      } catch (err) {
        if ((err as Error).message === "mfa required") setNeedMfa(true);
        throw err;
      }
    });
    if (r) {
      await signIn(r);
      router.replace("/dashboard");
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-4">
        <h1 className="text-lg font-semibold">Sign in</h1>
        {act.error && <Alert>{needMfa && act.error === "mfa required" ? "Enter the code from your authenticator app." : act.error}</Alert>}
        <Field label="Organization (workspace slug)" value={f.tenant_slug} onChange={(e) => setF({ ...f, tenant_slug: e.target.value })} required autoComplete="organization" />
        <Field label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required autoComplete="username" />
        <Field label="Password" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required autoComplete="current-password" />
        {needMfa && <Field label="Authenticator code" inputMode="numeric" value={f.mfa_code} onChange={(e) => setF({ ...f, mfa_code: e.target.value })} autoFocus autoComplete="one-time-code" />}
        <Btn type="submit" disabled={act.busy} className="w-full">
          {act.busy ? "Signing in…" : "Sign in"}
        </Btn>
        <p className="text-center text-sm text-muted">
          New organization? <Link href="/register" className="text-brand underline">Create a workspace</Link>
        </p>
        <p className="text-center text-xs text-muted">
          <Link href="/platform/login" className="underline">Platform staff sign-in</Link>
        </p>
      </form>
    </Card>
  );
}
