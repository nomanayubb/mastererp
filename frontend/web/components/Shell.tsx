"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { Btn } from "./ui";

const NAV: { href: string; label: string; term?: string; feature?: string; action?: string }[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/organization", label: "Organization", feature: "platform.org.companies", action: "view" },
  { href: "/members", label: "Members", term: "members", feature: "platform.users.members", action: "view" },
  { href: "/roles", label: "Roles & access", feature: "platform.authz.roles", action: "view" },
  { href: "/audit", label: "Audit log", feature: "platform.audit.log", action: "view" },
  { href: "/billing", label: "Billing", feature: "platform.billing.subscription", action: "view" },
  { href: "/configuration", label: "Configuration", feature: "platform.config.modules", action: "view" },
  { href: "/catalog", label: "Applications catalogue", feature: "platform.registry.catalog", action: "view" },
  { href: "/security", label: "Security" },
];

function NavLink({ href, label, path, onClick }: { href: string; label: string; path: string; onClick: () => void }) {
  const active = path === href || path.startsWith(href + "/");
  return (
    <Link href={href} onClick={onClick} aria-current={active ? "page" : undefined} className={`block rounded-md px-3 py-2 text-sm ${active ? "bg-bg font-semibold text-brand" : "text-ink hover:bg-bg"}`}>
      {label}
    </Link>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { tenant, apps, can, term, signOut } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const items = NAV.filter((n) => !n.feature || can(n.feature, n.action!));
  const close = () => setOpen(false);

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
        <nav aria-label="Main" className="px-2 pb-2">
          {items.map((n) => (
            <NavLink key={n.href} href={n.href} label={n.term ? term(n.term, n.label) : n.label} path={path} onClick={close} />
          ))}
        </nav>
        {apps.length > 0 && (
          <nav aria-label="Applications" className="border-t border-line px-2 py-2">
            <div className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted">Applications</div>
            {apps.map((a) => (
              <div key={a.slug}>
                <div className="px-3 pt-2 text-xs text-muted">{a.name}</div>
                {a.modules.map((m) => (
                  <NavLink key={`${a.slug}.${m.slug}`} href={`/apps/${a.slug}/${m.slug}`} label={m.name} path={path} onClick={close} />
                ))}
              </div>
            ))}
          </nav>
        )}
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
