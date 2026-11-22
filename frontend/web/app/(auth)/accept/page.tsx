"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Alert, Btn, Card, Field, useAction } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Form() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [token, setToken] = useState(useSearchParams().get("token") ?? "");
  const [f, setF] = useState({ display_name: "", password: "" });
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await act.run(() => api<{ access_token: string; refresh_token: string }>("/auth/accept-invitation", { body: { token, ...f }, auth: false }));
    if (r) {
      await signIn(r);
      router.replace("/dashboard");
    }
  }
  return (
    <Card>
      <form onSubmit={submit} className="space-y-4">
        <h1 className="text-lg font-semibold">Accept invitation</h1>
        {act.error && <Alert>{act.error}</Alert>}
        <Field label="Invitation token" value={token} onChange={(e) => setToken(e.target.value)} required />
        <Field label="Your name" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} />
        <Field label="Password" type="password" hint="New users: at least 12 characters. Existing users: your current password." value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        <Btn type="submit" disabled={act.busy} className="w-full">
          Join workspace
        </Btn>
      </form>
    </Card>
  );
}

export default function Accept() {
  return (
    <Suspense>
      <Form />
    </Suspense>
  );
}
