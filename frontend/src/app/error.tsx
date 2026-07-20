"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

const AUTO_RELOAD_KEY = "hy-chat:auto-reloaded-page-error";

function isLikelyStaleFrontend(error: Error) {
  const message = `${error.name} ${error.message}`.toLowerCase();
  return (
    message.includes("chunk") ||
    message.includes("dynamically imported") ||
    message.includes("module script")
  );
}

async function clearLocalStateAndReload() {
  try {
    window.localStorage.clear();
    window.sessionStorage.clear();
    if ("caches" in window) {
      const keys = await window.caches.keys();
      await Promise.all(keys.map((key) => window.caches.delete(key)));
    }
  } catch {
    // no-op
  } finally {
    window.location.replace("/");
  }
}

export default function PageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("页面异常", error);

    if (!isLikelyStaleFrontend(error)) return;
    try {
      const reloadKey = `${AUTO_RELOAD_KEY}:${window.location.href}`;
      if (window.sessionStorage.getItem(reloadKey)) return;
      window.sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
    } catch {
      window.location.reload();
    }
  }, [error]);

  return (
    <main className="bg-muted/30 flex min-h-dvh items-center justify-center p-6">
      <section className="bg-background w-full max-w-md rounded-2xl border p-6 text-center shadow-sm">
        <h1 className="text-xl font-semibold">页面暂时打不开</h1>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          页面加载时遇到异常。通常是前端刚更新后浏览器仍在使用旧资源，刷新页面即可恢复；如果仍然失败，可以清理本地状态后重新进入。
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Button
            variant="outline"
            onClick={() => window.location.reload()}
          >
            刷新页面
          </Button>
          <Button
            variant="outline"
            onClick={() => void clearLocalStateAndReload()}
          >
            清理本地状态
          </Button>
          <Button onClick={reset}>重试</Button>
        </div>
      </section>
    </main>
  );
}
