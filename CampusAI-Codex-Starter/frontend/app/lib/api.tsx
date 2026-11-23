"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

async function fetchCampusApi(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (cause) {
    if (cause instanceof TypeError) {
      throw new Error("CampusAI could not connect to its server. Check your connection and try again.");
    }
    throw cause;
  }
}

export type User = { id: number; email: string; full_name: string; role: string };
type AuthContextValue = {
  user: User | null;
  loading: boolean;
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
  login: (email: string, password: string) => Promise<User>;
  register: (fullName: string, email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

async function parseResponse<T>(response: Response): Promise<T> {
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? `Request failed (${response.status})`));
  }
  return body as T;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const response = await fetchCampusApi(`${API_BASE}/api/v1/auth/refresh`, { method: "POST", credentials: "include" });
    if (!response.ok) throw new Error("No active session");
    const session = await parseResponse<{ access_token: string; user: User }>(response);
    setAccessToken(session.access_token);
    setUser(session.user);
    return session;
  }, []);

  useEffect(() => {
    let active = true;
    fetchCampusApi(`${API_BASE}/api/v1/auth/refresh`, { method: "POST", credentials: "include" })
      .then(async (response) => {
        if (!response.ok) return;
        const session = await parseResponse<{ access_token: string; user: User }>(response);
        if (active) {
          setAccessToken(session.access_token);
          setUser(session.user);
        }
      })
      .catch(() => undefined)
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const api = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const send = (token: string | null) => fetchCampusApi(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
    let response = await send(accessToken);
    if (response.status === 401 && accessToken) {
      try {
        const session = await refresh();
        response = await send(session.access_token);
      } catch { /* Keep the original unauthorized response for the caller. */ }
    }
    return parseResponse<T>(response);
  }, [accessToken, refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const response = await fetchCampusApi(`${API_BASE}/api/v1/auth/login`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const session = await parseResponse<{ access_token: string; user: User }>(response);
    setAccessToken(session.access_token);
    setUser(session.user);
    return session.user;
  }, []);

  const register = useCallback(async (fullName: string, email: string, password: string) => {
    const response = await fetchCampusApi(`${API_BASE}/api/v1/auth/register`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: fullName, email, password }),
    });
    const session = await parseResponse<{ access_token: string; user: User }>(response);
    setAccessToken(session.access_token);
    setUser(session.user);
    return session.user;
  }, []);

  const logout = useCallback(async () => {
    await fetchCampusApi(`${API_BASE}/api/v1/auth/logout`, { method: "POST", credentials: "include" });
    setAccessToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, api, login, register, logout }), [user, loading, api, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}

export function RequireAuth({ children, roles }: { children: React.ReactNode; roles?: string[] }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (!loading && user && roles && !roles.includes(user.role)) router.replace(["administrator", "placement_officer"].includes(user.role) ? "/admin" : "/dashboard");
  }, [loading, user, roles, pathname, router]);
  if (loading || !user || (roles && !roles.includes(user.role))) return <div className="loading-panel">Loading your CampusAI workspace…</div>;
  return <>{children}</>;
}
