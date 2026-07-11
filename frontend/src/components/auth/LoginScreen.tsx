"use client";

import { FormEvent, useState } from "react";
import { LoaderCircle, MessageSquareText, UserRound } from "lucide-react";
import { useAuth } from "@/providers/Auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";

export function LoginScreen() {
  const { login, register, accounts, switchAccount } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      if (mode === "login") {
        await login(String(form.get("email")), String(form.get("password")));
      } else {
        await register(
          String(form.get("email")),
          String(form.get("password")),
          String(form.get("displayName")),
        );
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-4 sm:p-8">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-3xl border bg-white shadow-xl md:grid-cols-[1.05fr_1fr]">
        <section className="hidden bg-slate-950 p-10 text-white md:flex md:flex-col md:justify-between">
          <div className="flex items-center gap-3 text-xl font-semibold">
            <MessageSquareText className="size-7" /> HY-chat
          </div>
          <div>
            <h1 className="text-4xl leading-tight font-semibold">
              对话、知识库与工具，集中在一个安全工作台。
            </h1>
            <p className="mt-5 text-sm leading-6 text-slate-300">
              支持多会话、模型切换、RAG、Trace、对象存储与细粒度 AI 权限。
            </p>
          </div>
        </section>
        <section className="p-6 sm:p-10">
          <div className="mb-8 md:hidden">
            <div className="flex items-center gap-2 text-xl font-semibold">
              <MessageSquareText /> HY-chat
            </div>
          </div>
          <div className="mb-6 flex rounded-xl bg-slate-100 p-1">
            {(["login", "register"] as const).map((item) => (
              <button
                key={item}
                onClick={() => setMode(item)}
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium ${mode === item ? "bg-white shadow-sm" : "text-slate-500"}`}
              >
                {item === "login" ? "登录" : "注册"}
              </button>
            ))}
          </div>
          <h2 className="text-2xl font-semibold">
            {mode === "login" ? "欢迎回来" : "创建账号"}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            首个注册账号会自动获得管理员权限。
          </p>
          <form
            onSubmit={submit}
            className="mt-7 space-y-4"
          >
            {mode === "register" && (
              <Input
                name="displayName"
                placeholder="显示名称"
                required
              />
            )}
            <Input
              name="email"
              type="email"
              placeholder="邮箱"
              required
            />
            <PasswordInput
              name="password"
              placeholder="密码（至少 8 位）"
              minLength={mode === "register" ? 8 : 1}
              required
            />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button
              className="w-full"
              size="lg"
              disabled={loading}
            >
              {loading && <LoaderCircle className="animate-spin" />}
              {mode === "login" ? "登录" : "注册并登录"}
            </Button>
          </form>
          {accounts.length > 0 && (
            <div className="mt-8 border-t pt-5">
              <p className="mb-3 text-xs font-medium tracking-wide text-slate-400 uppercase">
                已保存账号
              </p>
              <div className="space-y-2">
                {accounts.map((account) => (
                  <button
                    key={account.user.id}
                    onClick={() => switchAccount(account.user.id)}
                    className="flex w-full items-center gap-3 rounded-xl border p-3 text-left hover:bg-slate-50"
                  >
                    <UserRound className="size-5 text-slate-500" />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {account.user.display_name}
                      </span>
                      <span className="block truncate text-xs text-slate-500">
                        {account.user.email}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
