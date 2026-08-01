"use client";

import React, { useEffect } from "react";
import dynamic from "next/dynamic";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { BrandLogo } from "@/components/brand-logo";

const loadChatWorkspace = () => import("@/components/chat-workspace");
const ChatWorkspace = dynamic(loadChatWorkspace, {
  loading: () => <WorkspaceLoadingScreen />,
});

function WorkspaceLoadingScreen() {
  return (
    <main
      className="bg-background flex min-h-dvh flex-col"
      aria-busy="true"
      aria-label="正在加载 HY-Agent"
    >
      <header className="flex h-16 items-center gap-3 border-b px-4 sm:px-6">
        <BrandLogo className="size-9 border" />
        <span className="text-lg font-semibold tracking-tight">HY-Agent</span>
      </header>
      <section className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-2xl animate-pulse space-y-4">
          <div className="bg-muted mx-auto h-7 w-44 rounded" />
          <div className="bg-muted/70 mx-auto h-4 w-72 max-w-full rounded" />
          <div className="bg-muted/60 mt-10 h-28 rounded-2xl" />
        </div>
      </section>
    </main>
  );
}

/** Keep the public/login shell small, then load the chat stack on demand. */
export default function ChatPage(): React.ReactNode {
  useEffect(() => {
    try {
      const accounts = window.localStorage.getItem("hy-chat:accounts");
      if (accounts && accounts !== "[]") void loadChatWorkspace();
    } catch {
      // Private browsing can disable localStorage; authentication still works.
    }
  }, []);

  return (
    <React.Suspense fallback={<WorkspaceLoadingScreen />}>
      <AuthBoundary>
        <ChatWorkspace />
      </AuthBoundary>
    </React.Suspense>
  );
}
