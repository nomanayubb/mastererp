"use client";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Shell } from "@/components/Shell";
import { useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [me, loading, router]);
  if (loading || !me) return <p className="p-8 text-muted">Loading…</p>;
  return <Shell>{children}</Shell>;
}
