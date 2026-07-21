"use client";

import Link from "next/link";
import {
  Activity,
  Code2,
  Files,
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
    <details className="relative shrink-0">
      <summary className="bg-background hover:bg-accent flex cursor-pointer list-none items-center gap-2 rounded-xl border px-2.5 py-2 text-sm">
        <span className="bg-primary text-primary-foreground flex size-7 items-center justify-center rounded-full">
          {user.display_name.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden max-w-28 truncate sm:block">
          {user.display_name}
        </span>
      </summary>
      <div className="bg-popover text-popover-foreground absolute right-0 z-50 mt-2 w-64 max-w-[calc(100vw-1rem)] rounded-2xl border p-2 shadow-xl">
        <div className="flex items-start justify-between gap-2 border-b px-3 py-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{user.display_name}</p>
            <p className="text-muted-foreground truncate text-xs">
              {user.email}
            </p>
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
                  className="hover:bg-accent flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm"
                >
                  <UserRound className="size-4" /> 切换到{" "}
                  {item.user.display_name}
                </button>
              ))}
          </div>
        )}
        <Link
          href="/traces"
          className="hover:bg-accent flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
        >
          <Activity className="size-4" /> 运行追踪
        </Link>
        <Link
          href="/files"
          className="hover:bg-accent flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
        >
          <Files className="size-4" /> 文件存储
        </Link>
        {user.role === "admin" && (
          <>
            <Link
              href="/coding-agent"
              className="hover:bg-accent flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
            >
              <Code2 className="size-4" /> Coding Agent
            </Link>
            <Link
              href="/admin"
              className="hover:bg-accent flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
            >
              <Shield className="size-4" /> 后台管理
            </Link>
          </>
        )}
        <button
          onClick={logout}
          className="text-destructive hover:bg-destructive/10 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm"
        >
          <LogOut className="size-4" /> 退出当前账号
        </button>
      </div>
    </details>
  );
}
