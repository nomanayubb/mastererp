"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert, Btn, Card, Field, useAction } from "@/components/ui";
import { api, setTokens } from "@/lib/api";

export default function StaffLogin() {
  const router = useRouter();
  const [f, setF] = useState({ email: "", password: "", mfa_code: "" });
  const [needMfa, setNeedMfa] = useState(false);
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await act.run(async () => {
      try {
        return await api<{ access_token: string }>("/platform/auth/login", { realm: "staff", auth: false, body: { ...f, mfa_code: f.mfa_code || undefined } });
      } catch (err) {
        if ((err as Error).message === "mfa required") setNeedMfa(true);
        throw err;
      }
    });
    if (r) {
      setTokens("staff", r);
      router.replace("/platform/tenants");
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
      <div className="mb-6 text-center">
        <div className="text-2xl font-semibold">UEOS Platform</div>
        <p className="mt-1 text-sm text-muted">Staff console</p>
      </div>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          {act.error && <Alert>{needMfa && act.error === "mfa required" ? "Enter your authenticator code." : act.error}</Alert>}
          <Field label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required autoComplete="username" />
          <Field label="Password" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required autoComplete="current-password" />
          {needMfa && <Field label="Authenticator code" inputMode="numeric" value={f.mfa_code} onChange={(e) => setF({ ...f, mfa_code: e.target.value })} autoFocus />}
          <Btn type="submit" disabled={act.busy} className="w-full">Sign in</Btn>
          <p className="text-center text-xs text-muted"><Link href="/login" className="underline">Customer sign-in</Link></p>
        </form>
      </Card>
    </main>
  );
}
