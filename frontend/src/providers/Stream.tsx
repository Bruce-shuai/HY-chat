import React, {
  createContext,
  useContext,
  ReactNode,
  useState,
  useEffect,
  useLayoutEffect,
  useMemo,
  useCallback,
  useRef,
} from "react";
import { useStream } from "@langchain/react";
import { type BaseMessage } from "@langchain/core/messages";
import { type UIMessage } from "@langchain/langgraph-sdk/react-ui";
import { useQueryState } from "nuqs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/brand-logo";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ArrowRight } from "lucide-react";
import { PasswordInput } from "@/components/ui/password-input";
import { getApiKey } from "@/lib/api-key";
import { useThreads } from "./Thread";
import { toast } from "sonner";
import { useAuth } from "./Auth";
import { resolveApiUrl } from "./client";
import {
  PRODUCTION_AGENT_ASSISTANT_ID,
  selectAgentApiUrl,
  selectAgentAssistantId,
  userBearerHeaders,
} from "./agent-api-policy";
import {
  AgentRunTimeoutError,
  AgentRunWatchdog,
  ResumedRunLifecycleTracker,
  resolveAgentRunTimeoutMs,
} from "@/lib/agent-run-timeout";
import {
  cancelActiveThreadRuns,
  cancelRunExactly,
  DEFAULT_RUN_CANCEL_TIMEOUT_MS,
} from "@/lib/agent-run-cancellation";

export type StateType = {
  messages: BaseMessage[];
  ui?: UIMessage[];
  context?: Record<string, unknown>;
  selected_model?: string;
};

const useTypedStream = useStream<StateType>;

type TypedStreamValue = ReturnType<typeof useTypedStream>;
type StreamContextType = TypedStreamValue & {
  isRunSettling: boolean;
};
const StreamContext = createContext<StreamContextType | undefined>(undefined);
const STREAM_CALLER_OPTIONS = { maxRetries: 1 };

type ActiveRun = {
  threadId: string;
  runId: string;
};

async function sleep(ms = 4000) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitAtMost(
  promise: Promise<unknown> | undefined,
  timeoutMs: number,
): Promise<void> {
  if (!promise) return;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      promise,
      new Promise<void>((resolve) => {
        timeout = setTimeout(resolve, timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

async function checkGraphStatus(
  apiUrl: string,
  apiKey: string | null,
  authScheme?: string,
  accessToken?: string | null,
): Promise<boolean> {
  try {
    const headers = new Headers();
    if (apiKey) headers.set("X-Api-Key", apiKey);
    if (authScheme) headers.set("X-Auth-Scheme", authScheme);
    const bearerHeaders = userBearerHeaders(apiUrl, accessToken);
    Object.entries(bearerHeaders).forEach(([name, value]) =>
      headers.set(name, value),
    );

    const res = await fetch(`${apiUrl}/info`, {
      headers,
    });

    return res.ok;
  } catch (e) {
    console.error(e);
    return false;
  }
}

const StreamSession = ({
  children,
  apiKey,
  apiUrl,
  assistantId,
  authScheme,
  accessToken,
}: {
  children: ReactNode;
  apiKey: string | null;
  apiUrl: string;
  assistantId: string;
  authScheme?: string;
  accessToken?: string | null;
}) => {
  const [threadId, setThreadId] = useQueryState("threadId");
  const { getThreads, setThreads } = useThreads();
  const resolvedApiUrl = resolveApiUrl(apiUrl);
  const runTimeoutMs = useMemo(
    () => resolveAgentRunTimeoutMs(process.env.NEXT_PUBLIC_CHAT_RUN_TIMEOUT_MS),
    [],
  );
  const runWatchdogRef = useRef<AgentRunWatchdog | null>(null);
  runWatchdogRef.current ??= new AgentRunWatchdog(runTimeoutMs);
  const watchdogThreadIdRef = useRef<string | null>(threadId ?? null);
  const wasStreamLoadingRef = useRef(false);
  const approvalLifecycleUnsubscribeRef = useRef<(() => void) | null>(null);
  const [controllerGeneration, setControllerGeneration] = useState(0);
  const controllerGenerationRef = useRef(controllerGeneration);
  controllerGenerationRef.current = controllerGeneration;
  const controllerRunThreadIdsRef = useRef(
    new Map<number, string | null>([[controllerGeneration, threadId ?? null]]),
  );
  const callbackGeneration = controllerGeneration;
  const callerOptions = useMemo(() => {
    // A new object intentionally replaces the SDK controller after a forced stop.
    void controllerGeneration;
    return { ...STREAM_CALLER_OPTIONS };
  }, [controllerGeneration]);
  const activeRunRef = useRef<ActiveRun | null>(null);
  const currentThreadIdRef = useRef<string | null>(threadId ?? null);
  const previousQueryThreadIdRef = useRef<string | null>(threadId ?? null);
  const internalQueryThreadIdRef = useRef<string | null>(null);
  const runThreadIdRef = useRef<string | null>(threadId ?? null);
  const cancellationThreadIdRef = useRef<string | null>(null);
  const cancellationGenerationRef = useRef(0);
  const streamRef = useRef<TypedStreamValue | null>(null);
  const mountedRef = useRef(true);
  const isRunSettlingRef = useRef(false);
  const [isRunSettling, setIsRunSettling] = useState(false);
  const [timeoutState, setTimeoutState] = useState<{
    threadId: string | null;
    error: AgentRunTimeoutError;
  } | null>(null);

  const clearRunTimer = useCallback(() => {
    runWatchdogRef.current?.clear();
    watchdogThreadIdRef.current = null;
    approvalLifecycleUnsubscribeRef.current?.();
    approvalLifecycleUnsubscribeRef.current = null;
  }, []);

  const watchApprovalLifecycle = useCallback(
    (current: TypedStreamValue) => {
      approvalLifecycleUnsubscribeRef.current?.();
      approvalLifecycleUnsubscribeRef.current = null;

      const thread = current.getThread();
      if (!thread) return;

      const tracker = new ResumedRunLifecycleTracker();
      approvalLifecycleUnsubscribeRef.current = thread.onEvent((event) => {
        if (
          event.method !== "lifecycle" ||
          event.params.namespace.length !== 0
        ) {
          return;
        }
        if (tracker.observe(event.params.data?.event)) clearRunTimer();
      });
    },
    [clearRunTimer],
  );

  const cancelThreadRuns = useCallback(
    async (
      current: TypedStreamValue,
      targetThreadId: string,
      knownRunId?: string,
      transportCleanup?: Promise<unknown>,
    ) => {
      const generation = ++cancellationGenerationRef.current;
      cancellationThreadIdRef.current = targetThreadId;
      isRunSettlingRef.current = true;
      if (mountedRef.current) setIsRunSettling(true);

      try {
        await Promise.all([
          cancelActiveThreadRuns(
            current.client.runs,
            targetThreadId,
            knownRunId,
          ),
          waitAtMost(transportCleanup, DEFAULT_RUN_CANCEL_TIMEOUT_MS),
        ]);
      } finally {
        if (cancellationGenerationRef.current === generation) {
          cancellationThreadIdRef.current = null;
          isRunSettlingRef.current = false;
          if (mountedRef.current) setIsRunSettling(false);
        }
      }
    },
    [],
  );

  const stopCurrentRun = useCallback(
    async ({
      cancel = true,
      targetThreadId,
      resetController = false,
    }: {
      cancel?: boolean;
      targetThreadId?: string | null;
      resetController?: boolean;
    } = {}) => {
      clearRunTimer();
      const current = streamRef.current;
      if (!current) return;

      const target =
        targetThreadId ??
        runThreadIdRef.current ??
        current.threadId ??
        currentThreadIdRef.current;
      const activeRun =
        activeRunRef.current?.threadId === target ? activeRunRef.current : null;
      activeRunRef.current = null;

      const localStop = current
        .stop({ cancel: false })
        .catch((error) => console.warn("停止本地流式连接失败", error));
      const transportCleanup =
        cancel && resetController
          ? current
              .getThread()
              ?.close()
              .catch((error) => console.warn("关闭旧 Agent 连接失败", error))
          : undefined;
      if (cancel && resetController) {
        setControllerGeneration((generation) => {
          const nextGeneration = generation + 1;
          controllerRunThreadIdsRef.current.set(
            nextGeneration,
            current.threadId ?? currentThreadIdRef.current,
          );
          return nextGeneration;
        });
      }
      const remoteCancellation =
        cancel && target
          ? cancelThreadRuns(
              current,
              target,
              activeRun?.runId,
              transportCleanup,
            )
          : Promise.resolve();

      await Promise.all([localStop, remoteCancellation]);
    },
    [cancelThreadRuns, clearRunTimer],
  );

  const armRunWatchdog = useCallback(
    (targetThreadId: string | null) => {
      watchdogThreadIdRef.current = targetThreadId;
      setTimeoutState(null);
      runWatchdogRef.current?.start(() => {
        const timedThreadId =
          watchdogThreadIdRef.current ??
          runThreadIdRef.current ??
          streamRef.current?.threadId ??
          currentThreadIdRef.current;
        setTimeoutState({
          threadId: timedThreadId,
          error: new AgentRunTimeoutError(runTimeoutMs),
        });
        void stopCurrentRun({
          targetThreadId: timedThreadId,
          resetController: true,
        });
      });
    },
    [runTimeoutMs, stopCurrentRun],
  );

  const defaultHeaders = useMemo(
    () => ({
      ...(authScheme ? { "X-Auth-Scheme": authScheme } : {}),
      ...userBearerHeaders(resolvedApiUrl, accessToken),
    }),
    [authScheme, resolvedApiUrl, accessToken],
  );
  const streamValue = useTypedStream({
    apiUrl: resolvedApiUrl,
    apiKey: apiKey ?? undefined,
    assistantId,
    callerOptions,
    defaultHeaders,
    threadId: threadId ?? null,
    onThreadId: (id) => {
      internalQueryThreadIdRef.current = id;
      currentThreadIdRef.current = id;
      runThreadIdRef.current = id;
      controllerRunThreadIdsRef.current.set(callbackGeneration, id);
      if (
        runWatchdogRef.current?.isActive &&
        watchdogThreadIdRef.current === null
      ) {
        watchdogThreadIdRef.current = id;
      }
      setThreadId(id);
      // Refetch threads list when thread ID changes.
      // Wait for some seconds before fetching so we're able to get the new thread that was created.
      sleep().then(() => getThreads().then(setThreads).catch(console.error));
    },
    onCreated: ({ runId }) => {
      const current = streamRef.current;
      const activeThreadId =
        controllerRunThreadIdsRef.current.get(callbackGeneration) ??
        currentThreadIdRef.current;
      if (!current || !activeThreadId) return;

      const activeRun = { threadId: activeThreadId, runId };
      if (
        callbackGeneration !== controllerGenerationRef.current ||
        cancellationThreadIdRef.current === activeThreadId
      ) {
        void cancelRunExactly(current.client.runs, activeThreadId, runId);
        return;
      }
      activeRunRef.current = activeRun;
    },
    onCompleted: ({ runId }) => {
      if (callbackGeneration !== controllerGenerationRef.current) return;
      if (!runId || activeRunRef.current?.runId === runId) {
        activeRunRef.current = null;
        clearRunTimer();
      }
    },
  });
  streamRef.current = streamValue;

  useLayoutEffect(() => {
    const nextThreadId = threadId ?? null;
    const previousThreadId = previousQueryThreadIdRef.current;
    if (previousThreadId === nextThreadId) return;
    previousQueryThreadIdRef.current = nextThreadId;

    if (internalQueryThreadIdRef.current === nextThreadId) {
      internalQueryThreadIdRef.current = null;
      currentThreadIdRef.current = nextThreadId;
      return;
    }

    internalQueryThreadIdRef.current = null;
    const targetThreadId = runThreadIdRef.current ?? previousThreadId;
    const current = streamRef.current;
    const hasUnsettledRun =
      runWatchdogRef.current?.isActive ||
      current?.isLoading ||
      activeRunRef.current !== null;
    if (targetThreadId && hasUnsettledRun) {
      setTimeoutState(null);
      void stopCurrentRun({
        targetThreadId,
        resetController: true,
      });
    }

    currentThreadIdRef.current = nextThreadId;
    runThreadIdRef.current = nextThreadId;
  }, [stopCurrentRun, threadId]);

  const stopSafely = useCallback<StreamContextType["stop"]>(
    async (options) => {
      setTimeoutState(null);
      const cancel = options?.cancel ?? true;
      await stopCurrentRun({ cancel, resetController: cancel });
    },
    [stopCurrentRun],
  );

  const submitWithTimeout = useCallback<StreamContextType["submit"]>(
    async (input, options) => {
      if (isRunSettlingRef.current) return;
      const current = streamRef.current;
      if (!current) return;

      runThreadIdRef.current =
        options?.threadId ??
        current.threadId ??
        currentThreadIdRef.current ??
        null;
      controllerRunThreadIdsRef.current.set(
        controllerGenerationRef.current,
        runThreadIdRef.current,
      );
      activeRunRef.current = null;
      armRunWatchdog(runThreadIdRef.current);
      try {
        await current.submit(input, {
          ...options,
          multitaskStrategy: options?.multitaskStrategy ?? "reject",
        });
      } catch (error) {
        clearRunTimer();
        throw error;
      }
    },
    [armRunWatchdog, clearRunTimer],
  );

  const respondWithTimeout = useCallback<StreamContextType["respond"]>(
    async (response, options) => {
      if (isRunSettlingRef.current) return;
      const current = streamRef.current;
      if (!current) return;
      runThreadIdRef.current =
        current.threadId ?? currentThreadIdRef.current ?? null;
      armRunWatchdog(runThreadIdRef.current);
      watchApprovalLifecycle(current);
      try {
        await current.respond(response, options);
      } catch (error) {
        clearRunTimer();
        throw error;
      }
    },
    [armRunWatchdog, clearRunTimer, watchApprovalLifecycle],
  );

  const respondAllWithTimeout = useCallback<StreamContextType["respondAll"]>(
    async (responsesById, options) => {
      if (isRunSettlingRef.current) return;
      const current = streamRef.current;
      if (!current) return;
      runThreadIdRef.current =
        current.threadId ?? currentThreadIdRef.current ?? null;
      armRunWatchdog(runThreadIdRef.current);
      watchApprovalLifecycle(current);
      try {
        await current.respondAll(responsesById, options);
      } catch (error) {
        clearRunTimer();
        throw error;
      }
    },
    [armRunWatchdog, clearRunTimer, watchApprovalLifecycle],
  );

  useEffect(() => {
    const wasLoading = wasStreamLoadingRef.current;
    wasStreamLoadingRef.current = streamValue.isLoading;
    if (!streamValue.isLoading) {
      if (wasLoading) clearRunTimer();
      return;
    }

    const targetThreadId =
      runThreadIdRef.current ??
      streamValue.threadId ??
      currentThreadIdRef.current;
    armRunWatchdog(targetThreadId);
  }, [
    armRunWatchdog,
    clearRunTimer,
    streamValue.isLoading,
    streamValue.threadId,
  ]);

  const visibleTimeoutError =
    timeoutState?.threadId === streamValue.threadId
      ? timeoutState.error
      : undefined;
  const contextValue = useMemo<StreamContextType>(
    () => ({
      ...streamValue,
      error: visibleTimeoutError ?? streamValue.error,
      stop: stopSafely,
      submit: submitWithTimeout,
      respond: respondWithTimeout,
      respondAll: respondAllWithTimeout,
      isRunSettling,
    }),
    [
      streamValue,
      visibleTimeoutError,
      stopSafely,
      submitWithTimeout,
      respondWithTimeout,
      respondAllWithTimeout,
      isRunSettling,
    ],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearRunTimer();
      const current = streamRef.current;
      const targetThreadId =
        runThreadIdRef.current ??
        current?.threadId ??
        currentThreadIdRef.current;
      const knownRunId =
        activeRunRef.current?.threadId === targetThreadId
          ? activeRunRef.current.runId
          : undefined;
      const hasUnsettledRun =
        runWatchdogRef.current?.isActive ||
        current?.isLoading ||
        activeRunRef.current !== null ||
        isRunSettlingRef.current;
      if (current && hasUnsettledRun) {
        void current.stop({ cancel: false });
        if (targetThreadId) {
          void cancelActiveThreadRuns(
            current.client.runs,
            targetThreadId,
            knownRunId,
          );
        }
      }
    };
  }, [clearRunTimer]);

  useEffect(() => {
    checkGraphStatus(resolvedApiUrl, apiKey, authScheme, accessToken).then(
      (ok) => {
        if (!ok) {
          toast.error("连接图服务失败", {
            description: () => (
              <p>
                请确认图服务已运行在 <code>{resolvedApiUrl}</code>
                ，并且访问密钥已正确配置（如果连接的是线上图服务）。
              </p>
            ),
            duration: 10000,
            richColors: true,
            closeButton: true,
          });
        }
      },
    );
  }, [apiKey, resolvedApiUrl, authScheme, accessToken]);

  return (
    <StreamContext.Provider value={contextValue}>
      {children}
    </StreamContext.Provider>
  );
};

// Default values for the form
const DEFAULT_API_URL = "/api";
const DEFAULT_ASSISTANT_ID = PRODUCTION_AGENT_ASSISTANT_ID;
const AGENT_BUILDER_AUTH_SCHEME = "langsmith-api-key";

function buildStreamSessionKey({
  apiUrl,
  assistantId,
  authScheme,
  accessToken,
}: {
  apiUrl?: string;
  assistantId?: string;
  authScheme?: string;
  accessToken?: string | null;
}) {
  return [
    apiUrl ?? "",
    assistantId ?? "",
    authScheme ?? "",
    accessToken ?? "",
  ].join(":");
}

export const StreamProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const { accessToken } = useAuth();
  // Get environment variables
  const envApiUrl: string | undefined = process.env.NEXT_PUBLIC_API_URL;
  const envAssistantId: string | undefined =
    process.env.NEXT_PUBLIC_ASSISTANT_ID;
  const envAuthScheme: string | undefined = process.env.NEXT_PUBLIC_AUTH_SCHEME;

  // Use URL params with env var fallbacks
  const [apiUrl, setApiUrl] = useQueryState("apiUrl", {
    defaultValue: envApiUrl || "",
  });
  const [assistantId, setAssistantId] = useQueryState("assistantId", {
    defaultValue: envAssistantId || "",
  });
  const [authScheme, setAuthScheme] = useQueryState("authScheme", {
    defaultValue: envAuthScheme || "",
  });
  const [isAgentBuilder, setIsAgentBuilder] = useState(
    () =>
      (authScheme || envAuthScheme || "").toLowerCase() ===
      AGENT_BUILDER_AUTH_SCHEME,
  );

  // For API key, use localStorage with env var fallback
  const [apiKey, _setApiKey] = useState(() => {
    const storedKey = getApiKey();
    return storedKey || "";
  });

  const setApiKey = (key: string) => {
    try {
      window.localStorage.setItem("lg:chat:apiKey", key);
    } catch {
      // no-op
    }
    _setApiKey(key);
  };

  // Production ignores URL overrides and always uses the application-owned graph.
  const finalApiUrl = selectAgentApiUrl(apiUrl, envApiUrl);
  const finalAssistantId = selectAgentAssistantId(assistantId, envAssistantId);
  const finalAuthScheme = authScheme || envAuthScheme || "";
  const streamSessionKey = buildStreamSessionKey({
    apiUrl: finalApiUrl,
    assistantId: finalAssistantId,
    authScheme: finalAuthScheme,
    accessToken,
  });

  // Show the form if we: don't have an API URL, or don't have an assistant ID
  if (!finalApiUrl || !finalAssistantId) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center p-4">
        <div className="animate-in fade-in-0 zoom-in-95 bg-background flex max-w-3xl flex-col rounded-lg border shadow-lg">
          <div className="mt-14 flex flex-col gap-2 border-b p-6">
            <div className="flex flex-col items-start gap-2">
              <BrandLogo
                className="size-9 border"
                priority
              />
              <h1 className="text-xl font-semibold tracking-tight">HY-chat</h1>
            </div>
            <p className="text-muted-foreground">
              欢迎使用 HY-chat。开始前，请填写图服务地址与图标识。
            </p>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();

              const form = e.target as HTMLFormElement;
              const formData = new FormData(form);
              const apiUrl = formData.get("apiUrl") as string;
              const assistantId = formData.get("assistantId") as string;
              const apiKey = formData.get("apiKey") as string;

              setApiUrl(apiUrl);
              setApiKey(apiKey);
              setAssistantId(assistantId);
              setAuthScheme(isAgentBuilder ? AGENT_BUILDER_AUTH_SCHEME : "");

              form.reset();
            }}
            className="bg-muted/50 flex flex-col gap-6 p-6"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="apiUrl">
                服务地址<span className="text-rose-500">*</span>
              </Label>
              <p className="text-muted-foreground text-sm">
                图服务的访问地址，可以是本地服务，也可以是线上部署。
              </p>
              <Input
                id="apiUrl"
                name="apiUrl"
                className="bg-background"
                defaultValue={apiUrl || DEFAULT_API_URL}
                required
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="assistantId">
                助手或图标识<span className="text-rose-500">*</span>
              </Label>
              <p className="text-muted-foreground text-sm">
                用于读取会话并执行操作的图名称、图标识或助手标识。
              </p>
              <Input
                id="assistantId"
                name="assistantId"
                className="bg-background"
                defaultValue={assistantId || DEFAULT_ASSISTANT_ID}
                required
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="apiKey">访问密钥</Label>
              <p className="text-muted-foreground text-sm">
                如果使用本地图服务，这一项<strong>不是必填</strong>。
                该值会保存在浏览器本地存储中，仅用于认证发往图服务的请求。
              </p>
              <PasswordInput
                id="apiKey"
                name="apiKey"
                defaultValue={apiKey ?? ""}
                className="bg-background"
                placeholder="可选，线上服务使用"
              />
            </div>

            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="agentBuilderEnabled">使用智能体构建器</Label>
                  <p className="text-muted-foreground text-sm">
                    如果连接的是智能体构建器部署，请开启此项。
                  </p>
                </div>
                <Switch
                  id="agentBuilderEnabled"
                  checked={isAgentBuilder}
                  onCheckedChange={setIsAgentBuilder}
                />
              </div>
            </div>

            <div className="mt-2 flex justify-end">
              <Button
                type="submit"
                size="lg"
              >
                继续
                <ArrowRight className="size-5" />
              </Button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <StreamSession
      key={streamSessionKey}
      apiKey={apiKey}
      apiUrl={finalApiUrl}
      assistantId={finalAssistantId}
      authScheme={finalAuthScheme || undefined}
      accessToken={accessToken}
    >
      {children}
    </StreamSession>
  );
};

// Create a custom hook to use the context
export const useStreamContext = (): StreamContextType => {
  const context = useContext(StreamContext);
  if (context === undefined) {
    throw new Error("请在流式会话提供器内使用会话上下文");
  }
  return context;
};

export default StreamContext;
