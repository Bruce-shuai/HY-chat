"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  Database,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/providers/Auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { BrandLogo } from "@/components/brand-logo";
import { DistortedGlass } from "@/components/ui/distorted-glass";

function getLoginErrorMessage(reason: unknown) {
  const message = reason instanceof Error ? reason.message : String(reason);
  return /[\u4e00-\u9fff]/.test(message) ? message : "认证失败，请稍后重试。";
}

type AuthMode = "login" | "register" | "reset-request" | "reset-confirm";

const modeCopy: Record<
  AuthMode,
  { title: string; description: string; button: string }
> = {
  login: {
    title: "欢迎回来",
    description: "登录后继续使用你的会话、知识库和工具权限。",
    button: "登录",
  },
  register: {
    title: "创建账号",
    description: "首个注册账号会自动获得管理员权限。",
    button: "注册并登录",
  },
  "reset-request": {
    title: "找回密码",
    description: "输入注册邮箱后，系统会发送一次性密码重置链接。",
    button: "发送重置链接",
  },
  "reset-confirm": {
    title: "重置密码",
    description: "设置新密码后，旧登录凭证会自动失效。",
    button: "重置并登录",
  },
};

export function LoginScreen() {
  const {
    login,
    register,
    requestPasswordReset,
    resetPassword,
    accounts,
    switchAccount,
  } = useAuth();
  const searchParams = useSearchParams();
  const resetTokenParam = searchParams.get("resetToken") || "";
  const [mode, setMode] = useState<AuthMode>("login");
  const [resetToken, setResetToken] = useState(resetTokenParam);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!resetTokenParam) return;
    setResetToken(resetTokenParam);
    setMode("reset-confirm");
  }, [resetTokenParam]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");
    const form = new FormData(event.currentTarget);
    try {
      if (mode === "login") {
        await login(String(form.get("email")), String(form.get("password")));
      } else if (mode === "register") {
        await register(
          String(form.get("email")),
          String(form.get("password")),
          String(form.get("displayName")),
        );
      } else if (mode === "reset-request") {
        const result = await requestPasswordReset(String(form.get("email")));
        if (result.reset_token) {
          setResetToken(result.reset_token);
          setMode("reset-confirm");
          setNotice("已生成本地调试用重置口令，请设置新密码。");
        } else {
          setNotice(
            result.email_configured
              ? "如果该邮箱存在，你会收到一封密码重置邮件。"
              : "请求已提交。如果没有收到邮件，请联系管理员确认邮件服务配置。",
          );
        }
      } else {
        const password = String(form.get("password"));
        const confirmPassword = String(form.get("confirmPassword"));
        const token = String(form.get("token") || resetToken);
        if (password !== confirmPassword) {
          throw new Error("两次输入的新密码不一致");
        }
        await resetPassword(token, password);
      }
    } catch (reason) {
      console.error("认证失败", reason);
      setError(getLoginErrorMessage(reason));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="hy-login-ambient relative isolate flex min-h-dvh items-center justify-center overflow-hidden p-3 sm:p-8">
      <div
        aria-hidden="true"
        className="hy-dot-grid pointer-events-none absolute inset-0 opacity-70"
      />
      <div className="hy-glass-strong relative grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/15 shadow-2xl md:grid-cols-[1.08fr_1fr]">
        <section className="relative hidden min-h-[650px] overflow-hidden bg-[linear-gradient(145deg,rgba(5,23,20,0.96),rgba(11,24,38,0.93)_55%,rgba(27,24,55,0.94))] p-10 text-white md:flex md:flex-col md:justify-between lg:p-12">
          <div
            aria-hidden="true"
            className="absolute -top-24 -right-20 size-72 rounded-full bg-cyan-300/12 blur-3xl"
          />
          <div
            aria-hidden="true"
            className="absolute bottom-10 -left-20 size-64 rounded-full bg-emerald-300/12 blur-3xl"
          />
          <div className="relative z-10 flex items-center">
            <BrandLogo
              variant="wordmark"
              className="text-white"
              priority
            />
          </div>
          <div className="relative z-10 max-w-md">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/8 px-3 py-1.5 text-xs font-medium text-emerald-100">
              <Sparkles className="size-3.5" />
              你的智能工作台
            </div>
            <h1 className="text-4xl leading-[1.15] font-semibold tracking-tight lg:text-5xl">
              让想法与工具，在一个
              <span className="hy-accent-text">智能空间</span>
              里协作。
            </h1>
            <p className="mt-6 max-w-sm text-sm leading-7 text-slate-300">
              从日常对话到知识检索、文件处理与 Coding
              Agent，让复杂任务拥有清晰、可追踪的执行过程。
            </p>
            <div className="mt-8 grid gap-3 text-sm text-slate-200 sm:grid-cols-2">
              <div className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/6 px-3 py-2.5">
                <Database className="size-4 text-cyan-200" />
                知识与文件集中管理
              </div>
              <div className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/6 px-3 py-2.5">
                <ShieldCheck className="size-4 text-emerald-200" />
                权限与执行全程可控
              </div>
            </div>
          </div>
          <DistortedGlass
            tone="dark"
            className="absolute inset-x-0 bottom-0 hidden h-24 opacity-55 xl:block"
          />
        </section>
        <section className="relative bg-white/90 p-6 sm:p-10 lg:p-12 dark:bg-slate-950/88">
          <div className="absolute inset-x-0 top-0 hidden h-px bg-gradient-to-r from-transparent via-teal-300/60 to-transparent md:block" />
          <div className="mb-8 md:hidden">
            <div className="flex items-center">
              <BrandLogo
                variant="wordmark"
                className="text-foreground"
                priority
              />
            </div>
          </div>
          {mode === "login" || mode === "register" ? (
            <div className="hy-glass-control mb-8 flex rounded-xl border p-1">
              {(["login", "register"] as const).map((item) => (
                <button
                  key={item}
                  onClick={() => setMode(item)}
                  className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${mode === item ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {item === "login" ? "登录" : "注册"}
                </button>
              ))}
            </div>
          ) : null}
          <h2 className="text-3xl font-semibold tracking-tight">
            {modeCopy[mode].title}
          </h2>
          <p className="text-muted-foreground mt-2 text-sm leading-6">
            {modeCopy[mode].description}
          </p>
          <form
            onSubmit={submit}
            className="mt-7 space-y-4"
          >
            {mode === "register" && (
              <Input
                name="displayName"
                placeholder="显示名称"
                className="bg-background/75 h-11 rounded-xl"
                required
              />
            )}
            {mode !== "reset-confirm" && (
              <Input
                name="email"
                type="email"
                placeholder="邮箱"
                autoComplete="email"
                className="bg-background/75 h-11 rounded-xl"
                required
              />
            )}
            {mode === "reset-confirm" && (
              <Input
                name="token"
                value={resetToken}
                onChange={(event) => setResetToken(event.target.value)}
                placeholder="重置口令"
                className="bg-background/75 h-11 rounded-xl"
                required
              />
            )}
            {mode !== "reset-request" && (
              <PasswordInput
                name="password"
                placeholder={
                  mode === "reset-confirm"
                    ? "新密码（至少 8 位）"
                    : "密码（至少 8 位）"
                }
                minLength={mode === "login" ? 1 : 8}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                className="bg-background/75 h-11 rounded-xl"
                required
              />
            )}
            {mode === "reset-confirm" && (
              <PasswordInput
                name="confirmPassword"
                placeholder="确认新密码"
                minLength={8}
                autoComplete="new-password"
                className="bg-background/75 h-11 rounded-xl"
                required
              />
            )}
            {notice && (
              <p
                className="rounded-xl border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-sm text-emerald-700"
                aria-live="polite"
              >
                {notice}
              </p>
            )}
            {error && (
              <p
                className="rounded-xl border border-red-200 bg-red-50/80 px-3 py-2 text-sm text-red-700"
                role="alert"
              >
                {error}
              </p>
            )}
            <Button
              className="h-11 w-full rounded-xl bg-slate-950 shadow-lg shadow-slate-950/15 hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100"
              size="lg"
              disabled={loading}
            >
              {loading && <LoaderCircle className="animate-spin" />}
              {modeCopy[mode].button}
            </Button>
          </form>
          <div className="mt-4 flex justify-center">
            {mode === "login" ? (
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground text-sm"
                onClick={() => {
                  setError("");
                  setNotice("");
                  setMode("reset-request");
                }}
              >
                忘记密码？
              </button>
            ) : null}
            {mode === "reset-request" || mode === "reset-confirm" ? (
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground text-sm"
                onClick={() => {
                  setError("");
                  setNotice("");
                  setMode("login");
                }}
              >
                返回登录
              </button>
            ) : null}
          </div>
          {accounts.length > 0 && mode !== "reset-confirm" && (
            <div className="mt-8 border-t border-black/8 pt-5 dark:border-white/10">
              <p className="text-muted-foreground mb-3 text-xs font-medium tracking-wide uppercase">
                已保存账号
              </p>
              <div className="space-y-2">
                {accounts.map((account) => (
                  <button
                    key={account.user.id}
                    onClick={() => switchAccount(account.user.id)}
                    className="hy-glass-control hover:bg-muted/50 flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors"
                  >
                    <UserRound className="text-muted-foreground size-5" />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {account.user.display_name}
                      </span>
                      <span className="text-muted-foreground block truncate text-xs">
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
