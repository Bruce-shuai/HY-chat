"use client";

import { FormEvent, useEffect, useState } from "react";
import { LoaderCircle, UserRound } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/providers/Auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { BrandLogo } from "@/components/brand-logo";

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
    <main className="bg-muted/30 flex min-h-dvh items-center justify-center p-4 sm:p-8">
      <div className="bg-background grid w-full max-w-4xl overflow-hidden rounded-3xl border shadow-xl md:grid-cols-[1.05fr_1fr]">
        <section className="hidden bg-slate-950 p-10 text-white md:flex md:flex-col md:justify-between">
          <div className="flex items-center">
            <BrandLogo
              variant="wordmark"
              className="h-20 w-24 shadow-lg"
              priority
            />
          </div>
          <div>
            <h1 className="text-4xl leading-tight font-semibold">
              对话、知识库与工具，集中在一个安全工作台。
            </h1>
            <p className="mt-5 text-sm leading-6 text-slate-300">
              支持多会话、模型切换、知识库检索、运行追踪、对象存储与细粒度智能权限。
            </p>
          </div>
        </section>
        <section className="p-6 sm:p-10">
          <div className="mb-8 md:hidden">
            <div className="flex items-center">
              <BrandLogo
                variant="wordmark"
                className="h-20 w-24 border shadow-sm"
                priority
              />
            </div>
          </div>
          {mode === "login" || mode === "register" ? (
            <div className="bg-muted mb-6 flex rounded-xl p-1">
              {(["login", "register"] as const).map((item) => (
                <button
                  key={item}
                  onClick={() => setMode(item)}
                  className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium ${mode === item ? "bg-background shadow-sm" : "text-muted-foreground"}`}
                >
                  {item === "login" ? "登录" : "注册"}
                </button>
              ))}
            </div>
          ) : null}
          <h2 className="text-2xl font-semibold">{modeCopy[mode].title}</h2>
          <p className="text-muted-foreground mt-1 text-sm">
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
                required
              />
            )}
            {mode !== "reset-confirm" && (
              <Input
                name="email"
                type="email"
                placeholder="邮箱"
                required
              />
            )}
            {mode === "reset-confirm" && (
              <Input
                name="token"
                value={resetToken}
                onChange={(event) => setResetToken(event.target.value)}
                placeholder="重置口令"
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
                required
              />
            )}
            {mode === "reset-confirm" && (
              <PasswordInput
                name="confirmPassword"
                placeholder="确认新密码"
                minLength={8}
                required
              />
            )}
            {notice && <p className="text-sm text-emerald-700">{notice}</p>}
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button
              className="w-full"
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
            <div className="mt-8 border-t pt-5">
              <p className="text-muted-foreground mb-3 text-xs font-medium tracking-wide uppercase">
                已保存账号
              </p>
              <div className="space-y-2">
                {accounts.map((account) => (
                  <button
                    key={account.user.id}
                    onClick={() => switchAccount(account.user.id)}
                    className="hover:bg-muted/30 flex w-full items-center gap-3 rounded-xl border p-3 text-left"
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
