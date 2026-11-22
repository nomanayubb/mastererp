"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { Btn } from "./ui";

const NAV: { href: string; label: string; feature?: string; action?: string }[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/organization", label: "Organization", feature: "platform.org.companies", action: "view" },
  { href: "/members", label: "Members", feature: "platform.users.members", action: "view" },
  { href: "/roles", label: "Roles & access", feature: "platform.authz.roles", action: "view" },
  { href: "/audit", label: "Audit log", feature: "platform.audit.log", action: "view" },
  { href: "/billing", label: "Billing", feature: "platform.billing.subscription", action: "view" },
  { href: "/catalog", label: "Applications", feature: "platform.registry.catalog", action: "view" },
  { href: "/security", label: "Security" },
];

export function Shell({ children }: { children: ReactNode }) {
  const { tenant, can, signOut } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const items = NAV.filter((n) => !n.feature || can(n.feature, n.action!));

  return (
    <div className="min-h-screen md:flex">
      <header className="flex items-center justify-between border-b border-line bg-surface px-4 py-3 md:hidden">
        <strong>UEOS</strong>
        <Btn variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="sidebar">
          Menu
        </Btn>
      </header>
      <aside id="sidebar" className={`${open ? "block" : "hidden"} w-full shrink-0 border-r border-line bg-surface md:block md:w-60`}>
        <div className="hidden px-4 py-4 md:block">
          <div className="text-base font-semibold">UEOS</div>
          <div className="mt-0.5 truncate text-xs text-muted">{tenant?.name ?? "…"}</div>
        </div>
        <nav aria-label="Main" className="px-2 pb-4">
          {items.map((n) => {
            const active = path === n.href || path.startsWith(n.href + "/");
            return (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
                aria-current={active ? "page" : undefined}
                className={`block rounded-md px-3 py-2 text-sm ${active ? "bg-bg font-semibold text-brand" : "text-ink hover:bg-bg"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-line px-4 py-3">
          <Btn
            variant="ghost"
            className="w-full"
            onClick={async () => {
              await signOut();
              router.replace("/login");
            }}
          >
            Sign out
          </Btn>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
    </div>
  );
}
