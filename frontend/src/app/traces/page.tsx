"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Activity, ArrowLeft, Clock, Database, X } from "lucide-react";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/Auth";

type Trace = {
  id: string;
  name: string;
  span_type: "model" | "tool";
  status: string;
  model_name?: string;
  tool_name?: string;
  total_tokens: number;
  latency_ms?: number;
  started_at: string;
  input?: unknown;
  output?: unknown;
  error_message?: string;
};

function TraceContent() {
  const { authFetch, user } = useAuth();
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selected, setSelected] = useState<Trace | null>(null);
  const [spanType, setSpanType] = useState("");
  const [loading, setLoading] = useState(true);
  const backend =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const load = useCallback(async () => {
    setLoading(true);
    const query = spanType ? `?span_type=${spanType}` : "";
    const response = await authFetch(`${backend}/traces${query}`);
    if (response.ok) setTraces((await response.json()).traces || []);
    setLoading(false);
  }, [authFetch, backend, spanType]);

  useEffect(() => {
    load();
  }, [load]);

  const open = async (trace: Trace) => {
    const response = await authFetch(`${backend}/traces/${trace.id}`);
    setSelected(response.ok ? await response.json() : trace);
  };

  return (
    <main className="min-h-dvh bg-slate-50">
      <header className="sticky top-0 z-20 border-b bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="rounded-lg p-2 hover:bg-slate-100"
            aria-label="返回聊天"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <Activity className="size-5" />
          <div className="min-w-0 flex-1">
            <h1 className="font-semibold">运行 Trace</h1>
            <p className="truncate text-xs text-slate-500">{user?.email}</p>
          </div>
          <AccountMenu />
        </div>
      </header>
      <div className="mx-auto max-w-7xl p-4 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {["", "model", "tool"].map((type) => (
            <Button
              key={type || "all"}
              variant={spanType === type ? "default" : "outline"}
              size="sm"
              onClick={() => setSpanType(type)}
            >
              {type === "model" ? "模型" : type === "tool" ? "工具" : "全部"}
            </Button>
          ))}
          <Button
            variant="ghost"
            size="sm"
            onClick={load}
          >
            刷新
          </Button>
        </div>
        <section className="overflow-hidden rounded-2xl border bg-white">
          {loading ? (
            <p className="p-8 text-center text-sm text-slate-500">加载中…</p>
          ) : traces.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">
              还没有 Trace，发送一条消息后会出现在这里。
            </p>
          ) : (
            <div className="divide-y">
              {traces.map((trace) => (
                <button
                  key={trace.id}
                  onClick={() => open(trace)}
                  className="grid w-full gap-2 p-4 text-left hover:bg-slate-50 sm:grid-cols-[minmax(0,1fr)_110px_110px_180px] sm:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`size-2 rounded-full ${trace.status === "success" ? "bg-emerald-500" : trace.status === "error" ? "bg-red-500" : "bg-amber-500"}`}
                      />
                      <p className="truncate font-medium">{trace.name}</p>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-500">
                      {trace.model_name || trace.tool_name || trace.span_type}
                    </p>
                  </div>
                  <span className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock className="size-3.5" /> {trace.latency_ms ?? 0} ms
                  </span>
                  <span className="flex items-center gap-1 text-xs text-slate-500">
                    <Database className="size-3.5" /> {trace.total_tokens}{" "}
                    tokens
                  </span>
                  <time className="text-xs text-slate-500">
                    {new Date(trace.started_at).toLocaleString()}
                  </time>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
      {selected && (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-black/20"
          onClick={() => setSelected(null)}
        >
          <aside
            className="h-full w-full overflow-y-auto bg-white p-5 shadow-2xl sm:max-w-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{selected.name}</h2>
                <p className="text-xs text-slate-500">{selected.id}</p>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="rounded-lg p-2 hover:bg-slate-100"
              >
                <X className="size-5" />
              </button>
            </div>
            {selected.error_message && (
              <div className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">
                {selected.error_message}
              </div>
            )}
            <h3 className="mb-2 text-sm font-semibold">输入</h3>
            <pre className="mb-5 overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">
              {JSON.stringify(selected.input, null, 2)}
            </pre>
            <h3 className="mb-2 text-sm font-semibold">输出</h3>
            <pre className="overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">
              {JSON.stringify(selected.output, null, 2)}
            </pre>
          </aside>
        </div>
      )}
    </main>
  );
}

export default function TracesPage() {
  return (
    <AuthBoundary>
      <TraceContent />
    </AuthBoundary>
  );
}
