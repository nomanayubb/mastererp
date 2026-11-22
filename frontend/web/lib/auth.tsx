"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, can as canFn, getTokens, setTokens, type Permission } from "./api";

type Me = { user_id: string; tenant_id: string; permissions: Permission[] };
type Tenant = { id: string; slug: string; name: string; status: string };
type Ctx = {
  me: Me | null;
  tenant: Tenant | null;
  loading: boolean;
  can: (key: string, action: string) => boolean;
  signIn: (tokens: { access_token: string; refresh_token?: string }) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthCtx = createContext<Ctx>(null as unknown as Ctx);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!getTokens("tenant")) {
      setMe(null);
      setTenant(null);
      setLoading(false);
      return;
    }
    try {
      const m = await api<Me>("/authz/me");
      setMe(m);
      setTenant(await api<Tenant>("/tenants/current").catch(() => null));
    } catch {
      setTokens("tenant", null);
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

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
  };
  const can = (key: string, action: string) => !!me && canFn(me.permissions, key, action);

  return <AuthCtx.Provider value={{ me, tenant, loading, can, signIn, signOut }}>{children}</AuthCtx.Provider>;
}
