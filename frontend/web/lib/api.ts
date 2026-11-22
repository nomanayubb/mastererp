// API client. Tenant and platform-staff sessions are separate realms with separate token storage.
export type Realm = "tenant" | "staff";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const KEY = { tenant: "ueos.tenant.tokens", staff: "ueos.staff.tokens" } as const;
type Tokens = { access_token: string; refresh_token?: string };

export function getTokens(realm: Realm): Tokens | null {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(localStorage.getItem(KEY[realm]) || "null");
  } catch {
    return null;
  }
}
export function setTokens(realm: Realm, t: Tokens | null) {
  if (t) localStorage.setItem(KEY[realm], JSON.stringify(t));
  else localStorage.removeItem(KEY[realm]);
}

function detail(body: unknown): { code: string; message: string } {
  const b = body as { title?: string; detail?: unknown } | null;
  if (b && Array.isArray(b.detail)) {
    return { code: "invalid", message: b.detail.map((d: { loc: unknown[]; msg: string }) => `${d.loc?.slice(1).join(".")}: ${d.msg}`).join("; ") };
  }
  const d = typeof b?.detail === "string" ? b.detail : "request_failed";
  return { code: d, message: d.replace(/_/g, " ") };
}

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  const t = getTokens("tenant");
  if (!t?.refresh_token) return false;
  refreshing ??= fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      setTokens("tenant", await r.json());
      return true;
    })
    .catch(() => false)
    .finally(() => (refreshing = null));
  return refreshing;
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; realm?: Realm; auth?: boolean } = {}): Promise<T> {
  const realm = opts.realm ?? "tenant";
  const go = () =>
    fetch(`/api/v1${path}`, {
      method: opts.method ?? (opts.body ? "POST" : "GET"),
      headers: {
        ...(opts.body !== undefined ? { "content-type": "application/json" } : {}),
        ...(opts.auth === false ? {} : getTokens(realm)?.access_token ? { authorization: `Bearer ${getTokens(realm)!.access_token}` } : {}),
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  let r = await go();
  if (r.status === 401 && realm === "tenant" && opts.auth !== false && (await refresh())) r = await go();
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const d = detail(body);
    throw new ApiError(r.status, d.code, d.message);
  }
  return body as T;
}

export type Permission = { feature_key: string; action: string; constraints: Record<string, unknown>; scope: Record<string, string[]>; role: string };

const matches = (pattern: string, key: string) => pattern === "*" || pattern === key || (pattern.endsWith(".*") && key.startsWith(pattern.slice(0, -1)));
/** UI hint only — the backend enforces every permission. */
export function can(perms: Permission[], key: string, action: string) {
  return perms.some((p) => matches(p.feature_key, key) && (p.action === "*" || p.action === action));
}
