"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ArrowLeft, Files, MessageSquare, Shield, Users } from "lucide-react";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthUser, useAuth } from "@/providers/Auth";

type Stats = {
  users: number;
  active_users: number;
  conversations: number;
  files: number;
  trace_spans: number;
};

function AdminContent() {
  const { user, authFetch } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [message, setMessage] = useState("");
  const backend =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

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
        <Link href="/">
          <Button>返回聊天</Button>
        </Link>
      </div>
    );
  }

  const save = async (event: FormEvent<HTMLFormElement>, target: AuthUser) => {
    event.preventDefault();
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
          allow_image_generation: form.get("images") === "on",
          allow_high_cost_tools: form.get("high_cost") === "on",
        }),
      },
    );
    if (!userResponse.ok || !policyResponse.ok) {
      const error = !userResponse.ok
        ? await userResponse.json()
        : await policyResponse.json();
      setMessage(error.detail || "保存失败");
    } else {
      setMessage("已保存");
      load();
    }
  };

  const cards = [
    ["用户", stats?.users ?? 0, Users],
    ["活跃账号", stats?.active_users ?? 0, Shield],
    ["会话", stats?.conversations ?? 0, MessageSquare],
    ["文件", stats?.files ?? 0, Files],
  ] as const;

  return (
    <main className="min-h-dvh bg-slate-50">
      <header className="sticky top-0 z-20 border-b bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="rounded-lg p-2 hover:bg-slate-100"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <Shield className="size-5" />
          <h1 className="flex-1 font-semibold">HY-chat 后台管理</h1>
          <AccountMenu />
        </div>
      </header>
      <div className="mx-auto max-w-7xl p-4 sm:p-6">
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {cards.map(([label, value, Icon]) => (
            <div
              key={label}
              className="rounded-2xl border bg-white p-4"
            >
              <Icon className="mb-4 size-5 text-slate-500" />
              <p className="text-2xl font-semibold">{value}</p>
              <p className="text-xs text-slate-500">{label}</p>
            </div>
          ))}
        </section>
        <div className="mt-6 flex items-center justify-between">
          <h2 className="text-lg font-semibold">账号与 AI 权限</h2>
          {message && <span className="text-sm text-slate-500">{message}</span>}
        </div>
        <section className="mt-3 space-y-3">
          {users.map((item) => (
            <form
              key={item.id}
              onSubmit={(event) => save(event, item)}
              className="rounded-2xl border bg-white p-4 sm:p-5"
            >
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-medium">{item.display_name}</h3>
                  <p className="text-xs text-slate-500">{item.email}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs">
                  已用 {item.policy.tokens_used.toLocaleString()} tokens
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <label className="text-xs text-slate-500">
                  角色
                  <select
                    name="role"
                    defaultValue={item.role}
                    className="mt-1 h-9 w-full rounded-md border bg-white px-2 text-sm"
                  >
                    <option value="user">普通用户</option>
                    <option value="admin">管理员</option>
                  </select>
                </label>
                <label className="text-xs text-slate-500">
                  每分钟请求数
                  <Input
                    name="rpm"
                    type="number"
                    defaultValue={item.policy.rpm_limit}
                    className="mt-1"
                  />
                </label>
                <label className="text-xs text-slate-500">
                  月 Token 配额
                  <Input
                    name="quota"
                    type="number"
                    defaultValue={item.policy.monthly_token_quota}
                    className="mt-1"
                  />
                </label>
                <label className="text-xs text-slate-500 sm:col-span-2 lg:col-span-1">
                  允许模型
                  <Input
                    name="models"
                    defaultValue={item.policy.allowed_models.join(", ")}
                    className="mt-1"
                  />
                </label>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
                <label>
                  <input
                    name="is_active"
                    type="checkbox"
                    defaultChecked={item.is_active}
                    className="mr-2"
                  />
                  账号启用
                </label>
                <label>
                  <input
                    name="images"
                    type="checkbox"
                    defaultChecked={item.policy.allow_image_generation}
                    className="mr-2"
                  />
                  图片生成
                </label>
                <label>
                  <input
                    name="high_cost"
                    type="checkbox"
                    defaultChecked={item.policy.allow_high_cost_tools}
                    className="mr-2"
                  />
                  高成本工具
                </label>
                <Button
                  size="sm"
                  className="ml-auto"
                >
                  保存
                </Button>
              </div>
            </form>
          ))}
        </section>
      </div>
    </main>
  );
}

export default function AdminPage() {
  return (
    <AuthBoundary>
      <AdminContent />
    </AuthBoundary>
  );
}
