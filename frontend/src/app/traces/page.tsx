"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Clock,
  Database,
  RefreshCcw,
  X,
} from "lucide-react";
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

const TRACE_LABELS: Record<string, string> = {
  generate_image: "生成图片",
  get_stock_quote: "股票查询",
  get_weather: "天气查询",
  model: "模型",
  search_workspace_code: "搜索工作区代码",
  tool: "工具",
  web_search: "网页搜索",
};

function formatTraceLabel(value?: string) {
  if (!value) return "未知";
  const raw = value.trim();
  const withoutPrefix = raw.replace(/^(tool|model):/i, "");
  const normalized = withoutPrefix
    .trim()
    .replace(/[\s-]+/g, "_")
    .toLowerCase();
  if (TRACE_LABELS[normalized]) return TRACE_LABELS[normalized];
  if (/^model:/i.test(raw)) return `模型：${withoutPrefix}`;
  if (/^tool:/i.test(raw)) return `工具：${withoutPrefix}`;
  return withoutPrefix;
}

function getTraceSubtitle(trace: Trace) {
  if (trace.model_name) return `模型：${trace.model_name}`;
  if (trace.tool_name) return `工具：${formatTraceLabel(trace.tool_name)}`;
  return formatTraceLabel(trace.span_type);
}

function parseJsonLikeString(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed || !["{", "["].includes(trimmed[0])) return value;

  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function normalizeJsonValue(
  value: unknown,
  seen = new WeakSet<object>(),
): unknown {
  if (typeof value === "string") {
    const parsed = parseJsonLikeString(value);
    return parsed === value ? value : normalizeJsonValue(parsed, seen);
  }

  if (Array.isArray(value)) {
    return value.map((item) => normalizeJsonValue(item, seen));
  }

  if (value && typeof value === "object") {
    if (seen.has(value)) return "[循环引用]";
    seen.add(value);

    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        normalizeJsonValue(item, seen),
      ]),
    );
  }

  return value;
}

function formatJson(value: unknown) {
  try {
    const formatted = JSON.stringify(normalizeJsonValue(value), null, 2);
    return formatted ?? String(value);
  } catch {
    return String(value);
  }
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <pre className="overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs leading-relaxed break-words whitespace-pre-wrap text-slate-100">
        {formatJson(value)}
      </pre>
    </section>
  );
}

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
    <main className="bg-muted/30 min-h-dvh">
      <header className="bg-background/90 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="hover:bg-muted rounded-lg p-2"
            aria-label="返回聊天"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <Activity className="size-5" />
          <div className="min-w-0 flex-1">
            <h1 className="font-semibold">运行追踪</h1>
            <p className="text-muted-foreground truncate text-xs">
              {user?.email}
            </p>
          </div>
          <AccountMenu />
        </div>
      </header>
      <div className="mx-auto max-w-7xl p-4 sm:p-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div
            className="bg-background inline-flex w-fit max-w-full rounded-md border p-1 shadow-xs"
            aria-label="追踪类型"
          >
            {["", "model", "tool"].map((type) => (
              <Button
                key={type || "all"}
                variant={spanType === type ? "default" : "ghost"}
                size="sm"
                className={`h-7 rounded-sm px-3 shadow-none ${
                  spanType === type
                    ? "hover:bg-primary/90 hover:text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                aria-pressed={spanType === type}
                onClick={() => setSpanType(type)}
              >
                {type === "model" ? "模型" : type === "tool" ? "工具" : "全部"}
              </Button>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-center gap-1.5 sm:w-auto"
            disabled={loading}
            onClick={load}
          >
            <RefreshCcw
              className={`size-3.5 ${loading ? "animate-spin" : ""}`}
            />
            刷新
          </Button>
        </div>
        <section className="bg-background overflow-hidden rounded-2xl border">
          {loading ? (
            <p className="text-muted-foreground p-8 text-center text-sm">
              加载中…
            </p>
          ) : traces.length === 0 ? (
            <p className="text-muted-foreground p-8 text-center text-sm">
              还没有运行追踪，发送一条消息后会出现在这里。
            </p>
          ) : (
            <div className="divide-y">
              {traces.map((trace) => (
                <button
                  key={trace.id}
                  onClick={() => open(trace)}
                  className="hover:bg-muted/30 grid w-full gap-2 p-4 text-left sm:grid-cols-[minmax(0,1fr)_110px_110px_180px] sm:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`size-2 rounded-full ${trace.status === "success" ? "bg-emerald-500" : trace.status === "error" ? "bg-red-500" : "bg-amber-500"}`}
                      />
                      <p className="truncate font-medium">
                        {formatTraceLabel(trace.name)}
                      </p>
                    </div>
                    <p className="text-muted-foreground mt-1 truncate text-xs">
                      {getTraceSubtitle(trace)}
                    </p>
                  </div>
                  <span className="text-muted-foreground flex items-center gap-1 text-xs">
                    <Clock className="size-3.5" /> {trace.latency_ms ?? 0} 毫秒
                  </span>
                  <span className="text-muted-foreground flex items-center gap-1 text-xs">
                    <Database className="size-3.5" /> {trace.total_tokens} 标记
                  </span>
                  <time className="text-muted-foreground text-xs">
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
            className="bg-background h-full w-full overflow-y-auto p-5 shadow-2xl sm:max-w-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">
                  {formatTraceLabel(selected.name)}
                </h2>
                <p className="text-muted-foreground mt-1 text-xs">
                  <span className="font-medium">追踪编号：</span>
                  <span className="break-all">{selected.id}</span>
                </p>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="hover:bg-muted rounded-lg p-2"
              >
                <X className="size-5" />
              </button>
            </div>
            {selected.error_message && (
              <div className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">
                {selected.error_message}
              </div>
            )}
            <div className="space-y-5">
              <JsonBlock
                title="输入"
                value={selected.input}
              />
              <JsonBlock
                title="输出"
                value={selected.output}
              />
            </div>
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
