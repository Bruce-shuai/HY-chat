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

export type PasswordResetRequestResult = {
  status: "ok";
  email_configured: boolean;
  reset_token?: string | null;
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
  changePassword: (
    currentPassword: string,
    newPassword: string,
  ) => Promise<void>;
  requestPasswordReset: (email: string) => Promise<PasswordResetRequestResult>;
  resetPassword: (token: string, newPassword: string) => Promise<void>;
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

function isPolicy(value: unknown): value is Policy {
  if (!value || typeof value !== "object") return false;
  const policy = value as Partial<Policy>;
  return (
    Array.isArray(policy.allowed_models) &&
    typeof policy.rpm_limit === "number" &&
    typeof policy.monthly_token_quota === "number" &&
    typeof policy.tokens_used === "number" &&
    typeof policy.quota_reset_at === "string" &&
    typeof policy.allow_high_cost_tools === "boolean"
  );
}

function isAccount(value: unknown): value is Account {
  if (!value || typeof value !== "object") return false;
  const account = value as Partial<Account>;
  const user = account.user as Partial<AuthUser> | undefined;
  return (
    typeof account.access_token === "string" &&
    typeof account.refresh_token === "string" &&
    typeof account.expires_in === "number" &&
    !!user &&
    typeof user.id === "string" &&
    typeof user.email === "string" &&
    typeof user.display_name === "string" &&
    (user.role === "admin" || user.role === "user") &&
    typeof user.is_active === "boolean" &&
    typeof user.created_at === "string" &&
    isPolicy(user.policy)
  );
}

function errorMessageFromDetail(detail: unknown, fallback: string) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown } | undefined;
    if (typeof first?.msg === "string" && first.msg.trim()) return first.msg;
  }
  return fallback;
}

function safeGetLocalStorage(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSetLocalStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // no-op
  }
}

function safeRemoveLocalStorage(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // no-op
  }
}

function loadAccounts(): Account[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(safeGetLocalStorage(ACCOUNTS_KEY) || "[]");
    if (!Array.isArray(parsed)) {
      safeRemoveLocalStorage(ACCOUNTS_KEY);
      safeRemoveLocalStorage(ACTIVE_KEY);
      return [];
    }
    return parsed.filter(isAccount);
  } catch {
    safeRemoveLocalStorage(ACCOUNTS_KEY);
    safeRemoveLocalStorage(ACTIVE_KEY);
    return [];
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const persist = useCallback((next: Account[], nextActive?: string | null) => {
    const validAccounts = next.filter(isAccount);
    setAccounts(validAccounts);
    safeSetLocalStorage(ACCOUNTS_KEY, JSON.stringify(validAccounts));
    if (nextActive !== undefined) {
      const validNextActive = validAccounts.some(
        (item) => item.user.id === nextActive,
      )
        ? nextActive
        : null;
      setActiveId(validNextActive);
      if (validNextActive) safeSetLocalStorage(ACTIVE_KEY, validNextActive);
      else safeRemoveLocalStorage(ACTIVE_KEY);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      let stored = loadAccounts();
      const requested = safeGetLocalStorage(ACTIVE_KEY);
      let active: Account | undefined =
        stored.find((item) => item.user.id === requested) || stored[0];
      if (active) {
        const me = await fetch(`${backendUrl()}/auth/me`, {
          headers: { Authorization: `Bearer ${active.access_token}` },
        }).catch(() => null);
        if (me?.ok) {
          const user = await me.json();
          active = isAccount({ ...active, user })
            ? { ...active, user }
            : undefined;
        } else {
          const refreshed = await fetch(`${backendUrl()}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: active.refresh_token }),
          }).catch(() => null);
          if (refreshed?.ok) {
            const refreshedAccount = await refreshed.json();
            active = isAccount(refreshedAccount) ? refreshedAccount : undefined;
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
        safeSetLocalStorage(ACCOUNTS_KEY, JSON.stringify(stored));
        if (active) safeSetLocalStorage(ACTIVE_KEY, active.user.id);
        else safeRemoveLocalStorage(ACTIVE_KEY);
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
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(errorMessageFromDetail(result?.detail, "认证失败"));
      }
      if (!isAccount(result)) throw new Error("登录返回数据异常");
      saveAccount(result);
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
    const result = await response.json();
    if (!isAccount(result)) return null;
    const next = result;
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
    safeSetLocalStorage(ACTIVE_KEY, userId);
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

  const changePassword = async (
    currentPassword: string,
    newPassword: string,
  ) => {
    const response = await authFetch(`${backendUrl()}/auth/password/change`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(errorMessageFromDetail(result?.detail, "修改密码失败"));
    }
    if (!isAccount(result)) throw new Error("修改密码返回数据异常");
    saveAccount(result);
  };

  const requestPasswordReset = async (email: string) => {
    const response = await fetch(
      `${backendUrl()}/auth/password-reset/request`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      },
    );
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(
        errorMessageFromDetail(result?.detail, "找回密码请求失败"),
      );
    }
    return {
      status: "ok" as const,
      email_configured: Boolean(result?.email_configured),
      reset_token:
        typeof result?.reset_token === "string" ? result.reset_token : null,
    };
  };

  const resetPassword = async (token: string, newPassword: string) => {
    const response = await fetch(
      `${backendUrl()}/auth/password-reset/confirm`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          new_password: newPassword,
        }),
      },
    );
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(errorMessageFromDetail(result?.detail, "重置密码失败"));
    }
    if (!isAccount(result)) throw new Error("重置密码返回数据异常");
    saveAccount(result);
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
    changePassword,
    requestPasswordReset,
    resetPassword,
    switchAccount,
    logout,
    logoutAll,
    authFetch,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("请在认证提供器内使用账号上下文");
  return context;
}
