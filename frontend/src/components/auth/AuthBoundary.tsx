"use client";

import { ReactNode } from "react";
import { useAuth } from "@/providers/Auth";
import { LoginScreen } from "./LoginScreen";
import { BrandLogo } from "@/components/brand-logo";

export function AuthBoundary({ children }: { children: ReactNode }) {
  const { ready, user } = useAuth();
  if (!ready) {
    return (
      <main
        className="bg-background flex min-h-dvh items-center justify-center p-6"
        aria-busy="true"
      >
        <div className="animate-pulse text-center">
          <BrandLogo
            variant="wordmark"
            className="text-foreground"
            priority
          />
          <p className="text-muted-foreground mt-4 text-sm">正在恢复工作台…</p>
        </div>
      </main>
    );
  }
  if (!user) return <LoginScreen />;
  return children;
}
