"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock3,
  Code2,
  LoaderCircle,
  RefreshCcw,
  TerminalSquare,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Toaster } from "@/components/ui/sonner";
import { useAuth } from "@/providers/Auth";
import { ADMIN_CONTACT_TEXT } from "@/lib/admin-contact";
import { cn } from "@/lib/utils";

type AgentRunSummary = {
  id: string;
  task: string;
  workspace: string;
  status: string;
  final_output: string | null;
  error_message: string | null;
  created_at: string;
};

type ToolCallSummary = {
  tool_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  status: string;
  created_at: string;
};

type ModelCallSummary = {
  provider: string;
  model_name: string;
  status: string;
  latency_ms: number | null;
  created_at: string;
};

type AgentRunDetail = AgentRunSummary & {
  tool_calls: ToolCallSummary[];
  model_calls: ModelCallSummary[];
};

type ModelOption = {
  id: string;
  label: string;
  is_default: boolean;
};

const STATUS_LABELS: Record<string, string> = {
  failed: "失败",
  mock: "模拟",
  running: "运行中",
  success: "成功",
};

const TOOL_LABELS: Record<string, string> = {
  list_files: "扫描文件",
  read_file: "读取文件",
  search_code: "搜索代码",
};

function backendUrl() {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatStatus(value: string) {
  return STATUS_LABELS[value] ?? value;
}

function formatToolName(value: string) {
  return TOOL_LABELS[value] ?? value;
}

function getStatusTone(value: string) {
  if (["success", "mock"].includes(value)) return "success";
  if (["failed", "error"].includes(value)) return "error";
  return "running";
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

function RunStatusBadge({ status }: { status: string }) {
  const tone = getStatusTone(status);
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium",
        tone === "success" && "bg-emerald-50 text-emerald-700",
        tone === "error" && "bg-red-50 text-red-700",
        tone === "running" && "bg-amber-50 text-amber-700",
      )}
    >
      {tone === "success" ? (
        <CheckCircle2 className="size-3.5" />
      ) : tone === "error" ? (
        <AlertCircle className="size-3.5" />
      ) : (
        <LoaderCircle className="size-3.5 animate-spin" />
      )}
      {formatStatus(status)}
    </span>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold">{title}</h4>
      <pre className="max-h-80 overflow-auto rounded-lg bg-zinc-950 p-3 text-xs leading-relaxed break-words whitespace-pre-wrap text-zinc-100">
        {formatJson(value)}
      </pre>
    </section>
  );
}

function EmptyState({ loading }: { loading: boolean }) {
  return (
    <div className="text-muted-foreground flex flex-col items-center justify-center gap-2 p-10 text-center text-sm">
      {loading ? (
        <LoaderCircle className="size-5 animate-spin" />
      ) : (
        <Bot className="size-5" />
      )}
      <p>{loading ? "加载中..." : "还没有 Coding Agent 运行记录。"}</p>
    </div>
  );
}

function AccessDenied() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
      <Code2 className="text-muted-foreground size-8" />
      <p>需要管理员权限。</p>
      <p className="text-muted-foreground text-sm">{ADMIN_CONTACT_TEXT}</p>
      <Link href="/">
        <Button>返回聊天</Button>
      </Link>
    </main>
  );
}

function getRunStats(runs: AgentRunSummary[]) {
  return {
    total: runs.length,
    success: runs.filter((run) => run.status === "success").length,
    failed: runs.filter((run) => run.status === "failed").length,
    running: runs.filter((run) => run.status === "running").length,
  };
}

function RunDetailDrawer({
  run,
  onClose,
}: {
  run: AgentRunDetail;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/20"
      onClick={onClose}
    >
      <aside
        className="bg-background h-full w-full overflow-y-auto p-5 shadow-2xl sm:max-w-3xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <RunStatusBadge status={run.status} />
              <time className="text-muted-foreground text-xs">
                {formatDate(run.created_at)}
              </time>
            </div>
            <h2 className="text-lg leading-7 font-semibold break-words">
              {run.task}
            </h2>
            <p className="text-muted-foreground mt-2 text-xs break-all">
              {run.workspace}
            </p>
          </div>
          <button
            onClick={onClose}
            className="hover:bg-muted rounded-lg p-2"
            title="关闭"
          >
            <X className="size-5" />
          </button>
        </div>

        {run.error_message && (
          <div className="mb-5 rounded-lg border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-700">
            {run.error_message}
          </div>
        )}

        <div className="space-y-6">
          <section>
            <h3 className="mb-2 text-sm font-semibold">最终输出</h3>
            <div className="bg-muted/40 min-h-24 rounded-lg border p-4 text-sm leading-7 whitespace-pre-wrap">
              {run.final_output || "暂无输出。"}
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-sm font-semibold">工具调用</h3>
            {run.tool_calls.length === 0 ? (
              <p className="text-muted-foreground rounded-lg border p-4 text-sm">
                暂无工具调用。
              </p>
            ) : (
              <div className="space-y-3">
                {run.tool_calls.map((call, index) => (
                  <details
                    key={`${call.tool_name}-${call.created_at}-${index}`}
                    className="overflow-hidden rounded-lg border"
                  >
                    <summary className="hover:bg-muted/40 flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 p-3">
                      <span className="flex items-center gap-2 text-sm font-medium">
                        <TerminalSquare className="size-4" />
                        {formatToolName(call.tool_name)}
                      </span>
                      <span className="text-muted-foreground flex items-center gap-2 text-xs">
                        <RunStatusBadge status={call.status} />
                        {formatDate(call.created_at)}
                      </span>
                    </summary>
                    <div className="grid gap-4 border-t p-3 lg:grid-cols-2">
                      <JsonBlock
                        title="输入"
                        value={call.input}
                      />
                      <JsonBlock
                        title="输出"
                        value={call.output}
                      />
                    </div>
                  </details>
                ))}
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-3 text-sm font-semibold">模型调用</h3>
            {run.model_calls.length === 0 ? (
              <p className="text-muted-foreground rounded-lg border p-4 text-sm">
                暂无模型调用。
              </p>
            ) : (
              <div className="overflow-hidden rounded-lg border">
                <div className="divide-y">
                  {run.model_calls.map((call, index) => (
                    <div
                      key={`${call.model_name}-${call.created_at}-${index}`}
                      className="grid gap-2 p-3 text-sm sm:grid-cols-[minmax(0,1fr)_100px_110px_160px] sm:items-center"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {call.model_name}
                        </p>
                        <p className="text-muted-foreground text-xs">
                          {call.provider}
                        </p>
                      </div>
                      <RunStatusBadge status={call.status} />
                      <span className="text-muted-foreground flex items-center gap-1 text-xs">
                        <Clock3 className="size-3.5" />
                        {call.latency_ms ?? 0} 毫秒
                      </span>
                      <time className="text-muted-foreground text-xs">
                        {formatDate(call.created_at)}
                      </time>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}

function CodingAgentContent() {
  const { authFetch, user } = useAuth();
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<AgentRunDetail | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const backend = backendUrl();

  const stats = useMemo(() => getRunStats(runs), [runs]);

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    try {
      const response = await authFetch(`${backend}/coding-agent/runs`);
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(result?.detail || "运行记录加载失败");
      }
      setRuns(await response.json());
    } catch (error) {
      toast.error("运行记录加载失败", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setLoadingRuns(false);
    }
  }, [authFetch, backend]);

  const loadModels = useCallback(async () => {
    try {
      const response = await authFetch(`${backend}/models`);
      if (!response.ok) return;
      const payload = await response.json();
      const nextModels = (payload.models ?? []) as ModelOption[];
      setModels(nextModels);
      setSelectedModel(payload.current_model || nextModels[0]?.id || "");
    } catch {
      setModels([]);
    }
  }, [authFetch, backend]);

  useEffect(() => {
    if (user?.role !== "admin") return;
    loadRuns();
    loadModels();
  }, [loadModels, loadRuns, user?.role]);

  const openRun = async (run: AgentRunSummary) => {
    try {
      const response = await authFetch(
        `${backend}/coding-agent/runs/${run.id}`,
      );
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(result?.detail || "运行详情加载失败");
      }
      setSelectedRun(await response.json());
    } catch (error) {
      toast.error("运行详情加载失败", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const submitRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedTask = task.trim();
    const trimmedWorkspace = workspace.trim();
    if (!trimmedTask) return;

    setSubmitting(true);
    try {
      const response = await authFetch(`${backend}/coding-agent/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task: trimmedTask,
          workspace: trimmedWorkspace || undefined,
          model: selectedModel || undefined,
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail || "Coding Agent 运行失败");
      }

      toast.success("Coding Agent 运行完成");
      setTask("");
      await loadRuns();
      const runId = result?.run_id as string | undefined;
      if (runId) {
        const detailResponse = await authFetch(
          `${backend}/coding-agent/runs/${runId}`,
        );
        if (detailResponse.ok) setSelectedRun(await detailResponse.json());
      }
    } catch (error) {
      toast.error("Coding Agent 运行失败", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSubmitting(false);
    }
  };

  if (user?.role !== "admin") {
    return <AccessDenied />;
  }

  const statItems = [
    ["全部", stats.total],
    ["成功", stats.success],
    ["失败", stats.failed],
    ["运行中", stats.running],
  ] as const;

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
          <Code2 className="size-5" />
          <div className="min-w-0 flex-1">
            <h1 className="font-semibold">Coding Agent</h1>
            <p className="text-muted-foreground truncate text-xs">
              {user?.email}
            </p>
          </div>
          <AccountMenu />
        </div>
      </header>

      <div className="mx-auto max-w-7xl p-4 sm:p-6">
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <form
            onSubmit={submitRun}
            className="bg-background rounded-lg border p-4 sm:p-5"
          >
            <div className="mb-4 flex items-center gap-2">
              <Bot className="text-muted-foreground size-5" />
              <h2 className="font-semibold">新建运行</h2>
            </div>
            <div className="grid gap-4">
              <label className="text-muted-foreground text-xs">
                任务
                <Textarea
                  value={task}
                  onChange={(event) => setTask(event.target.value)}
                  placeholder="例如：分析登录流程是否有权限绕过风险"
                  className="mt-1 min-h-28 text-sm"
                  disabled={submitting}
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_240px]">
                <label className="text-muted-foreground text-xs">
                  工作区
                  <Input
                    value={workspace}
                    onChange={(event) => setWorkspace(event.target.value)}
                    placeholder="/workspace"
                    className="mt-1"
                    disabled={submitting}
                  />
                </label>
                <label className="text-muted-foreground text-xs">
                  模型
                  <select
                    value={selectedModel}
                    onChange={(event) => setSelectedModel(event.target.value)}
                    className="bg-background mt-1 h-9 w-full rounded-md border px-2 text-sm"
                    disabled={submitting || models.length === 0}
                  >
                    {models.length === 0 ? (
                      <option value="">默认模型</option>
                    ) : (
                      models.map((model) => (
                        <option
                          key={model.id}
                          value={model.id}
                        >
                          {model.label}
                          {model.is_default ? "（默认）" : ""}
                        </option>
                      ))
                    )}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={loadRuns}
                  disabled={loadingRuns || submitting}
                >
                  <RefreshCcw
                    className={cn("size-4", loadingRuns && "animate-spin")}
                  />
                  刷新
                </Button>
                <Button
                  type="submit"
                  disabled={!task.trim() || submitting}
                >
                  {submitting ? (
                    <LoaderCircle className="animate-spin" />
                  ) : (
                    <TerminalSquare />
                  )}
                  {submitting ? "运行中..." : "运行"}
                </Button>
              </div>
            </div>
          </form>

          <section className="bg-background rounded-lg border p-4 sm:p-5">
            <h2 className="mb-4 font-semibold">运行概览</h2>
            <div className="grid grid-cols-2 gap-3">
              {statItems.map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-lg border p-3"
                >
                  <p className="text-2xl font-semibold">{value}</p>
                  <p className="text-muted-foreground text-xs">{label}</p>
                </div>
              ))}
            </div>
          </section>
        </section>

        <section className="bg-background mt-5 overflow-hidden rounded-lg border">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <h2 className="font-semibold">运行历史</h2>
            <Button
              variant="ghost"
              size="sm"
              onClick={loadRuns}
              disabled={loadingRuns || submitting}
            >
              <RefreshCcw
                className={cn("size-4", loadingRuns && "animate-spin")}
              />
              刷新
            </Button>
          </div>
          {runs.length === 0 ? (
            <EmptyState loading={loadingRuns} />
          ) : (
            <div className="divide-y">
              {runs.map((run) => (
                <button
                  key={run.id}
                  onClick={() => openRun(run)}
                  className="hover:bg-muted/30 grid w-full gap-2 p-4 text-left sm:grid-cols-[150px_minmax(0,1fr)_220px_180px] sm:items-center"
                >
                  <RunStatusBadge status={run.status} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{run.task}</p>
                    <p className="text-muted-foreground mt-1 truncate text-xs">
                      {run.final_output || run.error_message || run.id}
                    </p>
                  </div>
                  <span className="text-muted-foreground truncate text-xs">
                    {run.workspace}
                  </span>
                  <time className="text-muted-foreground text-xs">
                    {formatDate(run.created_at)}
                  </time>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      {selectedRun && (
        <RunDetailDrawer
          run={selectedRun}
          onClose={() => setSelectedRun(null)}
        />
      )}
    </main>
  );
}

export default function CodingAgentPage() {
  return (
    <AuthBoundary>
      <Toaster />
      <CodingAgentContent />
    </AuthBoundary>
  );
}
