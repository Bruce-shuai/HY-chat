import { type BaseMessage, isHumanMessage } from "@langchain/core/messages";
import { AlertTriangle, LoaderCircle } from "lucide-react";

import { DO_NOT_RENDER_ID_PREFIX } from "@/lib/ensure-tool-responses";
import { Button } from "../ui/button";
import { LocalErrorBoundary } from "./thread-error-boundary";
import { AssistantMessage, AssistantMessageLoading } from "./messages/ai";
import { HumanMessage } from "./messages/human";

type MessageListErrorFallbackProps = {
  threadId: string | null;
  reset: () => void;
  onNewThread: () => void;
  onOpenHistory: () => void;
};

type ThreadMessageListProps = {
  firstTokenReceived: boolean;
  hasInterrupt: boolean;
  hasNoAIOrToolMessages: boolean;
  isThreadLoading: boolean;
  isRunLoading: boolean;
  messages: BaseMessage[];
  resetKey: string;
  threadId: string | null;
  onNewThread: () => void;
  onOpenHistory: (reset: () => void) => void;
  onRegenerate: (parentCheckpointId: string | undefined) => void;
};

function ThreadLoadingState() {
  return (
    <div className="bg-muted text-muted-foreground mx-auto flex items-center gap-2 rounded-2xl px-4 py-2 text-sm">
      <LoaderCircle className="size-4 animate-spin" />
      <span>正在加载会话…</span>
    </div>
  );
}

function MessageListErrorFallback({
  threadId,
  reset,
  onNewThread,
  onOpenHistory,
}: MessageListErrorFallbackProps) {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col items-center justify-center rounded-xl border bg-zinc-50 p-6 text-center">
      <AlertTriangle className="mb-3 size-6 text-amber-600" />
      <h2 className="text-lg font-semibold">这个会话的消息暂时无法显示</h2>
      <p className="text-muted-foreground mt-2 text-sm leading-6">
        某条历史消息的数据格式触发了渲染异常。你可以先切到其他会话或新建会话，当前页面其他功能不会受影响。
      </p>
      {threadId ? (
        <p className="text-muted-foreground mt-3 max-w-full rounded-md bg-white px-3 py-2 text-xs break-all">
          线程编号：{threadId}
        </p>
      ) : null}
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        <Button
          variant="outline"
          onClick={onOpenHistory}
        >
          查看其他会话
        </Button>
        <Button
          variant="outline"
          onClick={reset}
        >
          重试显示
        </Button>
        <Button onClick={onNewThread}>新建会话</Button>
      </div>
    </div>
  );
}

function MessageItems({
  firstTokenReceived,
  hasInterrupt,
  hasNoAIOrToolMessages,
  isRunLoading,
  messages,
  onRegenerate,
}: Pick<
  ThreadMessageListProps,
  | "firstTokenReceived"
  | "hasInterrupt"
  | "hasNoAIOrToolMessages"
  | "isRunLoading"
  | "messages"
  | "onRegenerate"
>) {
  return (
    <>
      {messages
        .filter((message) => !message.id?.startsWith(DO_NOT_RENDER_ID_PREFIX))
        .map((message, index) =>
          isHumanMessage(message) ? (
            <HumanMessage
              key={message.id || `${message.type}-${index}`}
              message={message}
              isLoading={isRunLoading}
            />
          ) : (
            <AssistantMessage
              key={message.id || `${message.type}-${index}`}
              message={message}
              isLoading={isRunLoading}
              handleRegenerate={onRegenerate}
            />
          ),
        )}
      {hasNoAIOrToolMessages && hasInterrupt && (
        <AssistantMessage
          key="interrupt-msg"
          message={undefined}
          isLoading={isRunLoading}
          handleRegenerate={onRegenerate}
        />
      )}
      {isRunLoading && !firstTokenReceived && <AssistantMessageLoading />}
    </>
  );
}

export function ThreadMessageList({
  firstTokenReceived,
  hasInterrupt,
  hasNoAIOrToolMessages,
  isThreadLoading,
  isRunLoading,
  messages,
  resetKey,
  threadId,
  onNewThread,
  onOpenHistory,
  onRegenerate,
}: ThreadMessageListProps) {
  return (
    <LocalErrorBoundary
      label="消息列表"
      resetKey={resetKey}
      fallback={({ reset }) => (
        <MessageListErrorFallback
          threadId={threadId}
          reset={reset}
          onNewThread={onNewThread}
          onOpenHistory={() => onOpenHistory(reset)}
        />
      )}
    >
      {isThreadLoading ? (
        <ThreadLoadingState />
      ) : (
        <MessageItems
          firstTokenReceived={firstTokenReceived}
          hasInterrupt={hasInterrupt}
          hasNoAIOrToolMessages={hasNoAIOrToolMessages}
          isRunLoading={isRunLoading}
          messages={messages}
          onRegenerate={onRegenerate}
        />
      )}
    </LocalErrorBoundary>
  );
}
