"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Btn } from "@/components/ui";
import { api, getTokens, setTokens } from "@/lib/api";

const NAV = [
  { href: "/platform/tenants", label: "Tenants" },
  { href: "/platform/plans", label: "Plans & billing" },
  { href: "/platform/registry", label: "Registry" },
];

export default function Console({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [ok, setOk] = useState(false);

  useEffect(() => {
    if (!getTokens("staff")) return void router.replace("/platform/login");
    api("/platform/tenants", { realm: "staff" })
      .then(() => setOk(true))
      .catch(() => {
        setTokens("staff", null);
        router.replace("/platform/login");
      });
  }, [router]);

  if (!ok) return <p className="p-8 text-muted">Loading…</p>;
  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface px-4 py-3">
        <div className="flex items-center gap-6">
          <strong>UEOS Platform</strong>
          <nav aria-label="Platform" className="flex gap-1">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={path === n.href ? "page" : undefined} className={`rounded-md px-3 py-1.5 text-sm ${path === n.href ? "bg-bg font-semibold text-brand" : "hover:bg-bg"}`}>
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
        <Btn variant="ghost" onClick={() => { setTokens("staff", null); router.replace("/platform/login"); }}>Sign out</Btn>
      </header>
      <main className="p-4 md:p-8">{children}</main>
    </div>
  );
}
