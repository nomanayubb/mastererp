"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, can as canFn, getTokens, setTokens, type Permission } from "./api";

type Me = { user_id: string; tenant_id: string; permissions: Permission[] };
type Tenant = { id: string; slug: string; name: string; status: string };
export type NavFeature = { key: string; name: string; actions: string[]; status: string };
export type NavApp = { slug: string; name: string; modules: { slug: string; name: string; features: NavFeature[] }[] };
type Ctx = {
  me: Me | null;
  tenant: Tenant | null;
  apps: NavApp[];
  terms: Record<string, string>;
  loading: boolean;
  can: (key: string, action: string) => boolean;
  /** Tenant terminology (e.g. companies -> "Stores"); falls back to the default label. */
  term: (key: string, fallback: string) => string;
  reloadConfig: () => Promise<void>;
  signIn: (tokens: { access_token: string; refresh_token?: string }) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthCtx = createContext<Ctx>(null as unknown as Ctx);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [apps, setApps] = useState<NavApp[]>([]);
  const [terms, setTerms] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const reloadConfig = useCallback(async () => {
    const [n, t] = await Promise.all([
      api<NavApp[]>("/navigation").catch(() => [] as NavApp[]),
      api<Record<string, string>>("/config/terminology").catch(() => ({}) as Record<string, string>),
    ]);
    setApps(n);
    setTerms(t);
  }, []);

  const load = useCallback(async () => {
    if (!getTokens("tenant")) {
      setMe(null);
      setTenant(null);
      setApps([]);
      setTerms({});
      setLoading(false);
      return;
    }
    try {
      const m = await api<Me>("/authz/me");
      setMe(m);
      setTenant(await api<Tenant>("/tenants/current").catch(() => null));
      await reloadConfig();
    } catch {
      setTokens("tenant", null);
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, [reloadConfig]);

  useEffect(() => {
    load();
  }, [load]);

  const signIn: Ctx["signIn"] = async (t) => {
    setTokens("tenant", t);
    setLoading(true);
    await load();
  };
  const signOut = async () => {
    await api("/auth/logout", { method: "POST", body: {} }).catch(() => undefined);
    setTokens("tenant", null);
    setMe(null);
    setTenant(null);
    setApps([]);
    setTerms({});
  };
  const can = (key: string, action: string) => !!me && canFn(me.permissions, key, action);
  const term = (key: string, fallback: string) => terms[key] ?? fallback;

  return <AuthCtx.Provider value={{ me, tenant, apps, terms, loading, can, term, reloadConfig, signIn, signOut }}>{children}</AuthCtx.Provider>;
}
