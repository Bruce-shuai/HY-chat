"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  Activity,
  Code2,
  Files,
  KeyRound,
  LoaderCircle,
  LogOut,
  Shield,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/providers/Auth";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export function AccountMenu() {
  const { user, accounts, switchAccount, logout, changePassword } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [passwordSheetOpen, setPasswordSheetOpen] = useState(false);
  const [passwordFormKey, setPasswordFormKey] = useState(0);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState("");

  const submitPasswordChange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPasswordError("");
    const form = new FormData(event.currentTarget);
    const currentPassword = String(form.get("currentPassword"));
    const newPassword = String(form.get("newPassword"));
    const confirmPassword = String(form.get("confirmPassword"));
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致");
      return;
    }
    setPasswordLoading(true);
    try {
      await changePassword(currentPassword, newPassword);
      toast.success("密码已修改", {
        description: "其他设备上的旧登录凭证已经失效。",
      });
      setPasswordSheetOpen(false);
      setPasswordFormKey((current) => current + 1);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPasswordError(
        /[\u4e00-\u9fff]/.test(message)
          ? message
          : "修改密码失败，请稍后重试。",
      );
    } finally {
      setPasswordLoading(false);
    }
  };

  if (!user) return null;
  return (
    <>
      <details
        open={menuOpen}
        onToggle={(event) => setMenuOpen(event.currentTarget.open)}
        className="relative shrink-0"
      >
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
              <p className="truncate text-sm font-medium">
                {user.display_name}
              </p>
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
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false);
              setPasswordError("");
              setPasswordSheetOpen(true);
            }}
            className="hover:bg-accent flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm"
          >
            <KeyRound className="size-4" /> 修改密码
          </button>
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
      <Sheet
        open={passwordSheetOpen}
        onOpenChange={(open) => {
          setPasswordSheetOpen(open);
          if (!open) setPasswordError("");
        }}
      >
        <SheetContent
          side="right"
          className="overflow-y-auto"
        >
          <SheetHeader>
            <SheetTitle>修改密码</SheetTitle>
            <SheetDescription>
              修改后会保留当前会话，并让其他设备上的旧登录凭证失效。
            </SheetDescription>
          </SheetHeader>
          <form
            key={passwordFormKey}
            onSubmit={submitPasswordChange}
            className="flex flex-1 flex-col gap-4 px-4"
          >
            <div className="space-y-2">
              <Label htmlFor="currentPassword">当前密码</Label>
              <PasswordInput
                id="currentPassword"
                name="currentPassword"
                minLength={1}
                autoComplete="current-password"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="newPassword">新密码</Label>
              <PasswordInput
                id="newPassword"
                name="newPassword"
                minLength={8}
                autoComplete="new-password"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">确认新密码</Label>
              <PasswordInput
                id="confirmPassword"
                name="confirmPassword"
                minLength={8}
                autoComplete="new-password"
                required
              />
            </div>
            {passwordError && (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {passwordError}
              </p>
            )}
            <SheetFooter className="px-0">
              <Button
                type="submit"
                disabled={passwordLoading}
              >
                {passwordLoading && <LoaderCircle className="animate-spin" />}
                保存新密码
              </Button>
            </SheetFooter>
          </form>
        </SheetContent>
      </Sheet>
    </>
  );
}
