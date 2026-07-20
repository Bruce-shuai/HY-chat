import { validate } from "uuid";
import { getApiKey } from "@/lib/api-key";
import { Thread } from "@langchain/langgraph-sdk";
import { useQueryState } from "nuqs";
import {
  createContext,
  useContext,
  ReactNode,
  useCallback,
  useState,
  Dispatch,
  SetStateAction,
} from "react";
import { createClient } from "./client";
import { useAuth } from "./Auth";

type ConversationSummary = {
  thread_id: string;
  title: string;
};

interface ThreadContextType {
  getThreads: () => Promise<Thread[]>;
  renameThread: (thread: Thread, title: string) => Promise<Thread>;
  deleteThread: (threadId: string) => Promise<void>;
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
  threadsLoading: boolean;
  setThreadsLoading: Dispatch<SetStateAction<boolean>>;
}

const ThreadContext = createContext<ThreadContextType | undefined>(undefined);

function backendUrl() {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

function getThreadSearchMetadata(
  assistantId: string,
): { graph_id: string } | { assistant_id: string } {
  if (validate(assistantId)) {
    return { assistant_id: assistantId };
  } else {
    return { graph_id: assistantId };
  }
}

function withThreadTitle(thread: Thread, title: string): Thread {
  return {
    ...thread,
    metadata: {
      ...((thread.metadata ?? {}) as Record<string, unknown>),
      title,
    },
  };
}

async function readResponseError(response: Response, fallback: string) {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

export function ThreadProvider({ children }: { children: ReactNode }) {
  const { accessToken, authFetch } = useAuth();
  const envApiUrl: string | undefined = process.env.NEXT_PUBLIC_API_URL;
  const envAssistantId: string | undefined =
    process.env.NEXT_PUBLIC_ASSISTANT_ID;
  const envAuthScheme: string | undefined = process.env.NEXT_PUBLIC_AUTH_SCHEME;

  const [apiUrl] = useQueryState("apiUrl", {
    defaultValue: envApiUrl || "",
  });
  const [assistantId] = useQueryState("assistantId");
  const [authScheme] = useQueryState("authScheme", {
    defaultValue: envAuthScheme || "",
  });
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);

  const getClient = useCallback(() => {
    return createClient(
      apiUrl,
      getApiKey() ?? undefined,
      authScheme || undefined,
      accessToken,
    );
  }, [apiUrl, authScheme, accessToken]);

  const getThreads = useCallback(async (): Promise<Thread[]> => {
    const resolvedAssistantId = assistantId || envAssistantId;
    if (!apiUrl || !resolvedAssistantId) return [];
    const client = getClient();

    const graphThreads = await client.threads.search({
      metadata: {
        ...getThreadSearchMetadata(resolvedAssistantId),
      },
      limit: 100,
    });

    try {
      const response = await authFetch(`${backendUrl()}/conversations`);
      if (!response.ok) return graphThreads;
      const body = (await response.json()) as {
        conversations?: ConversationSummary[];
      };
      const titles = new Map(
        (body.conversations ?? []).map((conversation) => [
          conversation.thread_id,
          conversation.title,
        ]),
      );
      return graphThreads.map((thread) => {
        const title = titles.get(thread.thread_id);
        return title ? withThreadTitle(thread, title) : thread;
      });
    } catch {
      return graphThreads;
    }
  }, [apiUrl, assistantId, envAssistantId, getClient, authFetch]);

  const renameThread = useCallback(
    async (thread: Thread, title: string): Promise<Thread> => {
      if (!apiUrl) throw new Error("图服务地址未配置");
      const nextTitle = title.trim();
      if (!nextTitle) throw new Error("会话名称不能为空");

      const updated = await getClient().threads.update(thread.thread_id, {
        metadata: {
          ...(thread.metadata ?? {}),
          title: nextTitle,
        },
      });

      const response = await authFetch(
        `${backendUrl()}/conversations/by-thread/${encodeURIComponent(thread.thread_id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: nextTitle }),
        },
      );
      if (!response.ok && response.status !== 404) {
        throw new Error(
          await readResponseError(response, "后端会话名称同步失败"),
        );
      }

      const renamed = withThreadTitle({ ...thread, ...updated }, nextTitle);
      setThreads((current) =>
        current.map((item) =>
          item.thread_id === thread.thread_id ? renamed : item,
        ),
      );
      return renamed;
    },
    [apiUrl, authFetch, getClient],
  );

  const deleteThread = useCallback(
    async (threadId: string): Promise<void> => {
      if (!apiUrl) throw new Error("图服务地址未配置");
      await getClient().threads.delete(threadId);

      const response = await authFetch(
        `${backendUrl()}/conversations/by-thread/${encodeURIComponent(threadId)}`,
        { method: "DELETE" },
      );
      if (!response.ok && response.status !== 404) {
        throw new Error(await readResponseError(response, "后端会话删除失败"));
      }

      setThreads((current) =>
        current.filter((item) => item.thread_id !== threadId),
      );
    },
    [apiUrl, authFetch, getClient],
  );

  const value = {
    getThreads,
    renameThread,
    deleteThread,
    threads,
    setThreads,
    threadsLoading,
    setThreadsLoading,
  };

  return (
    <ThreadContext.Provider value={value}>{children}</ThreadContext.Provider>
  );
}

export function useThreads() {
  const context = useContext(ThreadContext);
  if (context === undefined) {
    throw new Error("请在会话提供器内使用会话列表上下文");
  }
  return context;
}
