"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  CircleDollarSign,
  Files,
  MessageSquare,
  Shield,
  Trash2,
  Users,
} from "lucide-react";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Toaster } from "@/components/ui/sonner";
import { AuthUser, useAuth } from "@/providers/Auth";
import { ADMIN_CONTACT_TEXT } from "@/lib/admin-contact";
import { backendUrl } from "@/lib/backend-url";

type Stats = {
  users: number;
  active_users: number;
  conversations: number;
  files: number;
  trace_spans: number;
};

type RowFeedback = {
  type: "success" | "error";
  text: string;
};

// Keep this description aligned with HIGH_COST_TOOLS in app/policies/service.py.
const HIGH_COST_TOOL_NAME = "股票行情查询";

function getResponseMessage(detail: unknown, fallback: string) {
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

function AdminContent() {
  const { user, authFetch } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [message, setMessage] = useState("");
  const [rowFeedback, setRowFeedback] = useState<Record<string, RowFeedback>>(
    {},
  );
  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const backend = backendUrl();

  const load = useCallback(async () => {
    const [usersResponse, statsResponse] = await Promise.all([
      authFetch(`${backend}/admin/users`),
      authFetch(`${backend}/admin/stats`),
    ]);
    if (usersResponse.ok) setUsers((await usersResponse.json()).users || []);
    if (statsResponse.ok) setStats(await statsResponse.json());
  }, [authFetch, backend]);

  useEffect(() => {
    load();
  }, [load]);

  if (user?.role !== "admin") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4">
        <p>需要管理员权限。</p>
        <p className="text-muted-foreground text-sm">{ADMIN_CONTACT_TEXT}</p>
        <Link href="/">
          <Button>返回聊天</Button>
        </Link>
      </div>
    );
  }

  const save = async (event: FormEvent<HTMLFormElement>, target: AuthUser) => {
    event.preventDefault();
    setSavingUserId(target.id);
    setMessage("");
    setRowFeedback((current) => {
      const next = { ...current };
      delete next[target.id];
      return next;
    });
    try {
      const form = new FormData(event.currentTarget);
      const userResponse = await authFetch(
        `${backend}/admin/users/${target.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            role: form.get("role"),
            is_active: form.get("is_active") === "on",
          }),
        },
      );
      const userResult = await userResponse.json().catch(() => null);
      if (!userResponse.ok) {
        const errorMessage = getResponseMessage(
          userResult?.detail,
          "账号信息保存失败",
        );
        setMessage(errorMessage);
        setRowFeedback((current) => ({
          ...current,
          [target.id]: { type: "error", text: errorMessage },
        }));
        toast.error("保存失败", {
          description: errorMessage,
        });
        return;
      }

      const policyResponse = await authFetch(
        `${backend}/admin/users/${target.id}/policy`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            allowed_models: String(form.get("models") || "")
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            rpm_limit: Number(form.get("rpm")),
            monthly_token_quota: Number(form.get("quota")),
            allow_high_cost_tools: form.get("high_cost") === "on",
          }),
        },
      );
      const policyResult = await policyResponse.json().catch(() => null);
      if (!policyResponse.ok) {
        const errorMessage = getResponseMessage(
          policyResult?.detail,
          "智能权限保存失败",
        );
        setMessage(errorMessage);
        setRowFeedback((current) => ({
          ...current,
          [target.id]: { type: "error", text: errorMessage },
        }));
        toast.error("保存失败", {
          description: errorMessage,
        });
        return;
      }

      const saved = policyResult as AuthUser;
      setUsers((current) =>
        current.map((item) => (item.id === saved.id ? saved : item)),
      );
      const successMessage = `已保存 ${saved.display_name} 的设置`;
      setMessage(successMessage);
      setRowFeedback((current) => ({
        ...current,
        [target.id]: { type: "success", text: "已保存" },
      }));
      toast.success("保存成功", {
        description: successMessage,
      });
    } catch {
      const errorMessage = "保存失败，请检查网络后稍后再试。";
      setMessage(errorMessage);
      setRowFeedback((current) => ({
        ...current,
        [target.id]: { type: "error", text: errorMessage },
      }));
      toast.error("保存失败", {
        description: errorMessage,
      });
    } finally {
      setSavingUserId(null);
    }
  };

  const remove = async (target: AuthUser) => {
    if (
      !window.confirm(
        `确定删除成员“${target.display_name}”吗？该成员的会话、文件和权限数据也会被删除。`,
      )
    ) {
      return;
    }
    setDeletingUserId(target.id);
    setMessage("");
    setRowFeedback((current) => {
      const next = { ...current };
      delete next[target.id];
      return next;
    });
    try {
      const response = await authFetch(`${backend}/admin/users/${target.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        const errorMessage = getResponseMessage(error?.detail, "删除失败");
        setMessage(errorMessage);
        toast.error("删除失败", {
          description: errorMessage,
        });
        return;
      }
      const successMessage = `已删除成员“${target.display_name}”`;
      setMessage(successMessage);
      toast.success("删除成功", {
        description: successMessage,
      });
      await load();
    } catch {
      const errorMessage = "删除失败，请检查网络后稍后再试。";
      setMessage(errorMessage);
      toast.error("删除失败", {
        description: errorMessage,
      });
    } finally {
      setDeletingUserId(null);
    }
  };

  const cards = [
    ["用户", stats?.users ?? 0, Users],
    ["活跃账号", stats?.active_users ?? 0, Shield],
    ["会话", stats?.conversations ?? 0, MessageSquare],
    ["文件", stats?.files ?? 0, Files],
  ] as const;

  return (
    <main className="bg-muted/30 min-h-dvh">
      <header className="bg-background/90 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-2 px-3 py-3 sm:gap-3 sm:px-6">
          <Link
            href="/"
            className="hover:bg-muted shrink-0 rounded-lg p-2"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <Shield className="size-5 shrink-0" />
          <h1 className="min-w-0 flex-1 truncate font-semibold">
            HY-Agent 后台管理
          </h1>
          <AccountMenu />
        </div>
      </header>
      <div className="mx-auto max-w-7xl p-3 sm:p-6">
        <section className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
          {cards.map(([label, value, Icon]) => (
            <div
              key={label}
              className="bg-background rounded-xl border p-3 sm:rounded-2xl sm:p-4"
            >
              <Icon className="text-muted-foreground mb-3 size-5 sm:mb-4" />
              <p className="text-xl font-semibold sm:text-2xl">{value}</p>
              <p className="text-muted-foreground text-xs">{label}</p>
            </div>
          ))}
        </section>
        <div className="mt-5 flex flex-col gap-1 sm:mt-6 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold">账号与智能权限</h2>
          {message && (
            <span className="text-muted-foreground text-sm">{message}</span>
          )}
        </div>
        <aside
          className="bg-muted/40 mt-3 flex items-start gap-3 rounded-xl border p-4"
          aria-labelledby="high-cost-tools-title"
        >
          <span className="bg-background flex size-9 shrink-0 items-center justify-center rounded-lg border">
            <CircleDollarSign
              className="text-muted-foreground size-5"
              aria-hidden="true"
            />
          </span>
          <div className="min-w-0">
            <h3
              id="high-cost-tools-title"
              className="text-sm font-medium"
            >
              高成本工具包含哪些功能？
            </h3>
            <p className="mt-1 text-sm">
              当前仅包含 1 项：
              <span className="font-medium">{HIGH_COST_TOOL_NAME}</span>
              （股票、ETF 和常见指数报价）。
            </p>
            <p className="text-muted-foreground mt-1 text-xs leading-5">
              此功能会调用外部行情服务，可能消耗第三方服务额度。关闭后只会拦截股票行情查询；普通聊天、网页搜索、天气查询和图片生成不受影响。
            </p>
          </div>
        </aside>
        <section className="mt-3 space-y-3">
          {users.map((item) => {
            const feedback = rowFeedback[item.id];
            return (
              <form
                key={[
                  item.id,
                  item.role,
                  item.is_active,
                  item.policy.rpm_limit,
                  item.policy.monthly_token_quota,
                  item.policy.allow_high_cost_tools,
                  item.policy.allowed_models.join("|"),
                ].join(":")}
                onSubmit={(event) => save(event, item)}
                className="bg-background rounded-xl border p-4 sm:rounded-2xl sm:p-5"
              >
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-medium">{item.display_name}</h3>
                    <p className="text-muted-foreground text-xs break-all">
                      {item.email}
                    </p>
                  </div>
                  <span className="bg-muted rounded-full px-2.5 py-1 text-xs">
                    已用 {item.policy.tokens_used.toLocaleString()} 个标记
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <label className="text-muted-foreground text-xs">
                    角色
                    <select
                      name="role"
                      defaultValue={item.role}
                      className="bg-background mt-1 h-9 w-full rounded-md border px-2 text-sm"
                    >
                      <option value="user">普通用户</option>
                      <option value="admin">管理员</option>
                    </select>
                  </label>
                  <label className="text-muted-foreground text-xs">
                    每分钟请求数
                    <Input
                      name="rpm"
                      type="number"
                      defaultValue={item.policy.rpm_limit}
                      className="mt-1"
                    />
                  </label>
                  <label className="text-muted-foreground text-xs">
                    月标记配额
                    <Input
                      name="quota"
                      type="number"
                      defaultValue={item.policy.monthly_token_quota}
                      className="mt-1"
                    />
                  </label>
                  <label className="text-muted-foreground text-xs sm:col-span-2 lg:col-span-1">
                    允许模型
                    <Input
                      name="models"
                      defaultValue={item.policy.allowed_models.join(", ")}
                      className="mt-1"
                    />
                  </label>
                </div>
                <div className="mt-4 flex flex-col gap-3 text-sm lg:flex-row lg:items-center">
                  <label className="flex items-center gap-2">
                    <input
                      name="is_active"
                      type="checkbox"
                      defaultChecked={item.is_active}
                      className="size-4 shrink-0"
                    />
                    账号启用
                  </label>
                  <div className="bg-muted/30 flex min-w-0 items-start gap-2 rounded-lg border px-3 py-2.5 lg:max-w-sm lg:flex-1">
                    <input
                      id={`high-cost-${item.id}`}
                      name="high_cost"
                      type="checkbox"
                      defaultChecked={item.policy.allow_high_cost_tools}
                      aria-describedby={`high-cost-description-${item.id}`}
                      className="mt-0.5 size-4 shrink-0"
                    />
                    <label
                      htmlFor={`high-cost-${item.id}`}
                      className="min-w-0 cursor-pointer"
                    >
                      <span className="block font-medium">
                        允许使用高成本工具
                      </span>
                      <span
                        id={`high-cost-description-${item.id}`}
                        className="text-muted-foreground mt-0.5 block text-xs"
                      >
                        当前包含：{HIGH_COST_TOOL_NAME}
                      </span>
                    </label>
                  </div>
                  <div className="flex w-full flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end lg:ml-auto lg:w-auto">
                    {feedback && (
                      <span
                        className={
                          feedback.type === "success"
                            ? "flex items-center gap-1 text-xs text-emerald-600 sm:justify-end"
                            : "text-destructive flex items-center gap-1 text-xs sm:justify-end"
                        }
                      >
                        {feedback.type === "success" ? (
                          <CheckCircle2 className="size-4" />
                        ) : (
                          <AlertCircle className="size-4" />
                        )}
                        {feedback.text}
                      </span>
                    )}
                    {item.id === user.id ? (
                      <span className="text-muted-foreground text-xs">
                        当前账号
                      </span>
                    ) : (
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        className="w-full sm:w-auto"
                        disabled={
                          deletingUserId === item.id || savingUserId === item.id
                        }
                        onClick={() => remove(item)}
                      >
                        <Trash2 className="size-4" />
                        {deletingUserId === item.id ? "删除中…" : "删除成员"}
                      </Button>
                    )}
                    <Button
                      type="submit"
                      size="sm"
                      className="w-full sm:w-auto"
                      disabled={savingUserId === item.id}
                    >
                      {savingUserId === item.id ? "保存中…" : "保存"}
                    </Button>
                  </div>
                </div>
              </form>
            );
          })}
        </section>
      </div>
    </main>
  );
}

export default function AdminPage() {
  return (
    <AuthBoundary>
      <Toaster />
      <AdminContent />
    </AuthBoundary>
  );
}
