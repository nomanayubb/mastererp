"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert, Btn, Card, Field, useAction } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 41);

export default function Register() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [f, setF] = useState({ tenant_name: "", slug: "", display_name: "", email: "", password: "" });
  const [slugTouched, setSlugTouched] = useState(false);
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await act.run(() => api<{ access_token: string; refresh_token: string }>("/auth/register", { body: f, auth: false }));
    if (r) {
      await signIn(r);
      router.replace("/dashboard");
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-4">
        <h1 className="text-lg font-semibold">Create your workspace</h1>
        {act.error && <Alert>{act.error}</Alert>}
        <Field
          label="Organization name"
          value={f.tenant_name}
          onChange={(e) => setF({ ...f, tenant_name: e.target.value, slug: slugTouched ? f.slug : slugify(e.target.value) })}
          required
        />
        <Field label="Workspace slug" hint="Used to sign in. Lowercase letters, digits, hyphens." value={f.slug} onChange={(e) => { setSlugTouched(true); setF({ ...f, slug: e.target.value }); }} required />
        <Field label="Your name" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} />
        <Field label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required autoComplete="username" />
        <Field label="Password" type="password" hint="At least 12 characters." value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required minLength={12} autoComplete="new-password" />
        <Btn type="submit" disabled={act.busy} className="w-full">
          {act.busy ? "Creating…" : "Create workspace"}
        </Btn>
        <p className="text-center text-sm text-muted">
          Already have one? <Link href="/login" className="text-brand underline">Sign in</Link>
        </p>
      </form>
    </Card>
  );
}
