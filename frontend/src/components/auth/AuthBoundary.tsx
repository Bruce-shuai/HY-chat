"use client";

import { ReactNode } from "react";
import { useAuth } from "@/providers/Auth";
import { LoginScreen } from "./LoginScreen";

export function AuthBoundary({ children }: { children: ReactNode }) {
  const { ready, user } = useAuth();
  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center">加载中…</div>
    );
  }
  if (!user) return <LoginScreen />;
  return children;
}
