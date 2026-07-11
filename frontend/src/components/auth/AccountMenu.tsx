"use client";

import Link from "next/link";
import {
  Activity,
  Files,
  Images,
  LogOut,
  Shield,
  UserRound,
} from "lucide-react";
import { useAuth } from "@/providers/Auth";
import { ThemeToggle } from "@/components/theme-toggle";

export function AccountMenu() {
  const { user, accounts, switchAccount, logout } = useAuth();
  if (!user) return null;
  return (
    <details className="relative">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl border bg-background px-2.5 py-2 text-sm hover:bg-accent">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary text-primary-foreground">
          {user.display_name.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden max-w-28 truncate sm:block">
          {user.display_name}
        </span>
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-64 rounded-2xl border bg-popover p-2 text-popover-foreground shadow-xl">
        <div className="flex items-start justify-between gap-2 border-b px-3 py-2">
          <div className="min-w-0">
          <p className="truncate text-sm font-medium">{user.display_name}</p>
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          </div>
          <ThemeToggle />
        </div>
        {accounts.length > 1 && (
          <div className="border-b py-2">
            {accounts
              .filter((item) => item.user.id !== user.id)
              .map((item) => (
                <button
                  key={item.user.id}
                  onClick={() => switchAccount(item.user.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-accent"
                >
                  <UserRound className="size-4" /> 切换到{" "}
                  {item.user.display_name}
                </button>
              ))}
          </div>
        )}
        <Link
          href="/traces"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-accent"
        >
          <Activity className="size-4" /> Trace
        </Link>
        <Link
          href="/images"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-accent"
        >
          <Images className="size-4" /> 图片工作台
        </Link>
        <Link
          href="/files"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-accent"
        >
          <Files className="size-4" /> 文件存储
        </Link>
        {user.role === "admin" && (
          <Link
            href="/admin"
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-accent"
          >
            <Shield className="size-4" /> 后台管理
          </Link>
        )}
        <button
          onClick={logout}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-destructive hover:bg-destructive/10"
        >
          <LogOut className="size-4" /> 退出当前账号
        </button>
      </div>
    </details>
  );
}
