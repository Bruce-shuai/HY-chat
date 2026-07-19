"use client";

import React, {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

export type Policy = {
  allowed_models: string[];
  rpm_limit: number;
  monthly_token_quota: number;
  tokens_used: number;
  quota_reset_at: string;
  allow_high_cost_tools: boolean;
};

export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "user";
  is_active: boolean;
  created_at: string;
  policy: Policy;
};

type Account = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: AuthUser;
};

type AuthContextValue = {
  ready: boolean;
  user: AuthUser | null;
  accounts: Account[];
  accessToken: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    displayName: string,
  ) => Promise<void>;
  switchAccount: (userId: string) => void;
  logout: () => void;
  logoutAll: () => Promise<void>;
  authFetch: (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<Response>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const ACCOUNTS_KEY = "hy-chat:accounts";
const ACTIVE_KEY = "hy-chat:active-account";

function backendUrl() {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

function loadAccounts(): Account[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(ACCOUNTS_KEY) || "[]");
  } catch {
    return [];
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const persist = useCallback((next: Account[], nextActive?: string | null) => {
    setAccounts(next);
    window.localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(next));
    if (nextActive !== undefined) {
      setActiveId(nextActive);
      if (nextActive) window.localStorage.setItem(ACTIVE_KEY, nextActive);
      else window.localStorage.removeItem(ACTIVE_KEY);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      let stored = loadAccounts();
      const requested = window.localStorage.getItem(ACTIVE_KEY);
      let active =
        stored.find((item) => item.user.id === requested) || stored[0];
      if (active) {
        const me = await fetch(`${backendUrl()}/auth/me`, {
          headers: { Authorization: `Bearer ${active.access_token}` },
        }).catch(() => null);
        if (me?.ok) {
          active = { ...active, user: await me.json() };
        } else {
          const refreshed = await fetch(`${backendUrl()}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: active.refresh_token }),
          }).catch(() => null);
          if (refreshed?.ok) {
            active = (await refreshed.json()) as Account;
          } else if (
            me &&
            [401, 403].includes(me.status) &&
            refreshed &&
            [400, 401, 403].includes(refreshed.status)
          ) {
            stored = stored.filter((item) => item.user.id !== active?.user.id);
            active = stored[0];
          }
        }
      }
      if (active) {
        stored = [
          active,
          ...stored.filter((item) => item.user.id !== active?.user.id),
        ];
      }
      if (!cancelled) {
        setAccounts(stored);
        setActiveId(active?.user.id || null);
        window.localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(stored));
        if (active) window.localStorage.setItem(ACTIVE_KEY, active.user.id);
        else window.localStorage.removeItem(ACTIVE_KEY);
        setReady(true);
      }
    };
    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const account = accounts.find((item) => item.user.id === activeId) || null;

  const saveAccount = useCallback(
    (next: Account) => {
      const updated = [
        next,
        ...accounts.filter((item) => item.user.id !== next.user.id),
      ];
      persist(updated, next.user.id);
    },
    [accounts, persist],
  );

  const submitAuth = useCallback(
    async (path: string, payload: Record<string, string>) => {
      const response = await fetch(`${backendUrl()}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "认证失败");
      saveAccount(result as Account);
    },
    [saveAccount],
  );

  const refresh = useCallback(async (): Promise<Account | null> => {
    if (!account) return null;
    const response = await fetch(`${backendUrl()}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: account.refresh_token }),
    });
    if (!response.ok) return null;
    const next = (await response.json()) as Account;
    saveAccount(next);
    return next;
  }, [account, saveAccount]);

  useEffect(() => {
    if (!account?.access_token) return;
    try {
      const encoded = account.access_token.split(".")[1];
      const raw = encoded.replace(/-/g, "+").replace(/_/g, "/");
      const normalized = raw.padEnd(Math.ceil(raw.length / 4) * 4, "=");
      const payload = JSON.parse(window.atob(normalized));
      const refreshIn = Math.max(
        5_000,
        payload.exp * 1000 - Date.now() - 60_000,
      );
      const timer = window.setTimeout(() => void refresh(), refreshIn);
      return () => window.clearTimeout(timer);
    } catch {
      return;
    }
  }, [account?.access_token, refresh]);

  const authFetch = useCallback(
    async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const headers = new Headers(init.headers);
      if (account?.access_token) {
        headers.set("Authorization", `Bearer ${account.access_token}`);
      }
      let response = await fetch(input, { ...init, headers });
      if (response.status === 401 && account?.refresh_token) {
        const next = await refresh();
        if (next) {
          headers.set("Authorization", `Bearer ${next.access_token}`);
          response = await fetch(input, { ...init, headers });
        }
      }
      return response;
    },
    [account, refresh],
  );

  const switchAccount = (userId: string) => {
    window.localStorage.setItem(ACTIVE_KEY, userId);
    window.location.href = "/";
  };

  const logout = () => {
    const remaining = accounts.filter((item) => item.user.id !== activeId);
    const nextId = remaining[0]?.user.id || null;
    persist(remaining, nextId);
    window.location.href = nextId ? "/" : "/";
  };

  const logoutAll = async () => {
    if (account) {
      await authFetch(`${backendUrl()}/auth/logout-all`, { method: "POST" });
    }
    logout();
  };

  const value: AuthContextValue = {
    ready,
    user: account?.user || null,
    accounts,
    accessToken: account?.access_token || null,
    login: (email, password) => submitAuth("/auth/login", { email, password }),
    register: (email, password, displayName) =>
      submitAuth("/auth/register", {
        email,
        password,
        display_name: displayName,
      }),
    switchAccount,
    logout,
    logoutAll,
    authFetch,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
