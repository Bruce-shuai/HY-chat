import React, {
  createContext,
  useContext,
  ReactNode,
  useState,
  useEffect,
  useMemo,
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

export type StateType = {
  messages: BaseMessage[];
  ui?: UIMessage[];
  context?: Record<string, unknown>;
  selected_model?: string;
};

const useTypedStream = useStream<StateType>;

type StreamContextType = ReturnType<typeof useTypedStream>;
const StreamContext = createContext<StreamContextType | undefined>(undefined);

async function sleep(ms = 4000) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

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
  const defaultHeaders = useMemo(
    () => ({
      ...(authScheme ? { "X-Auth-Scheme": authScheme } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    }),
    [authScheme, accessToken],
  );
  const streamValue = useTypedStream({
    apiUrl: resolvedApiUrl,
    apiKey: apiKey ?? undefined,
    assistantId,
    defaultHeaders,
    threadId: threadId ?? null,
    onThreadId: (id) => {
      setThreadId(id);
      // Refetch threads list when thread ID changes.
      // Wait for some seconds before fetching so we're able to get the new thread that was created.
      sleep().then(() => getThreads().then(setThreads).catch(console.error));
    },
  });

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
    <StreamContext.Provider value={streamValue}>
      {children}
    </StreamContext.Provider>
  );
};

// Default values for the form
const DEFAULT_API_URL = "/api";
const DEFAULT_ASSISTANT_ID = "hy-chat";
const AGENT_BUILDER_AUTH_SCHEME = "langsmith-api-key";

function buildStreamSessionKey({
  apiUrl,
  assistantId,
  authScheme,
  threadId,
}: {
  apiUrl?: string;
  assistantId?: string;
  authScheme?: string;
  threadId: string | null;
}) {
  return [
    apiUrl ?? "",
    assistantId ?? "",
    authScheme ?? "",
    threadId ?? "new-thread",
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
  const [threadId] = useQueryState("threadId");
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

  // Determine final values to use, prioritizing URL params then env vars
  const finalApiUrl = apiUrl || envApiUrl;
  const finalAssistantId = assistantId || envAssistantId;
  const finalAuthScheme = authScheme || envAuthScheme || "";
  const streamSessionKey = buildStreamSessionKey({
    apiUrl: finalApiUrl,
    assistantId: finalAssistantId,
    authScheme: finalAuthScheme,
    threadId,
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
