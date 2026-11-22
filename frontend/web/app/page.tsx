"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { me, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading) router.replace(me ? "/dashboard" : "/login");
  }, [me, loading, router]);
  return <p className="p-8 text-muted">Loading…</p>;
}
