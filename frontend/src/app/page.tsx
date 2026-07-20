"use client";

import { Thread } from "@/components/thread";
import { LocalErrorBoundary } from "@/components/thread/thread-error-boundary";
import { StreamProvider } from "@/providers/Stream";
import { ThreadProvider } from "@/providers/Thread";
import { ArtifactProvider } from "@/components/thread/artifact";
import { Toaster } from "@/components/ui/sonner";
import React from "react";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { Button } from "@/components/ui/button";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { BrandLogo } from "@/components/brand-logo";
import { useQueryState, parseAsBoolean } from "nuqs";

function ChatWorkspaceBoundary({ children }: { children: React.ReactNode }) {
  const [threadId, setThreadId] = useQueryState("threadId");
  const [, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );

  return (
    <LocalErrorBoundary
      label="会话工作区"
      resetKey={threadId ?? "new-thread"}
      fallback={({ reset }) => (
        <main className="bg-background flex h-dvh w-full flex-col">
          <header className="flex items-center justify-between border-b px-4 py-3">
            <button
              type="button"
              className="flex items-center gap-2"
              onClick={() => {
                void setThreadId(null);
                reset();
              }}
            >
              <BrandLogo className="size-9 border" />
              <span className="text-xl font-semibold tracking-tight">
                HY-chat
              </span>
            </button>
            <AccountMenu />
          </header>
          <section className="flex flex-1 items-center justify-center p-6">
            <div className="bg-background w-full max-w-lg rounded-xl border p-6 text-center shadow-sm">
              <h1 className="text-xl font-semibold">当前会话暂时打不开</h1>
              <p className="text-muted-foreground mt-3 text-sm leading-6">
                这个会话的数据触发了前端渲染异常，但不会影响其他会话。可以先切到新会话，或打开会话列表选择其他会话。
              </p>
              {threadId ? (
                <p className="text-muted-foreground mt-3 rounded-md bg-zinc-100 px-3 py-2 text-xs break-all">
                  线程编号：{threadId}
                </p>
              ) : null}
              <div className="mt-6 flex flex-wrap justify-center gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    void setThreadId(null);
                    void setChatHistoryOpen(true);
                    reset();
                  }}
                >
                  查看其他会话
                </Button>
                <Button
                  variant="outline"
                  onClick={reset}
                >
                  重试当前会话
                </Button>
                <Button
                  onClick={() => {
                    void setThreadId(null);
                    reset();
                  }}
                >
                  新建会话
                </Button>
              </div>
            </div>
          </section>
        </main>
      )}
    >
      {children}
    </LocalErrorBoundary>
  );
}

/** Compose the providers required by the main authenticated chat workspace. */
export default function ChatPage(): React.ReactNode {
  return (
    <React.Suspense fallback={<div>加载中...</div>}>
      <AuthBoundary>
        <Toaster />
        <ThreadProvider>
          <ChatWorkspaceBoundary>
            <StreamProvider>
              <ArtifactProvider>
                <Thread />
              </ArtifactProvider>
            </StreamProvider>
          </ChatWorkspaceBoundary>
        </ThreadProvider>
      </AuthBoundary>
    </React.Suspense>
  );
}
