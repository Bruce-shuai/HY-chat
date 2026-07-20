import { parsePartialJson } from "@langchain/core/output_parsers";
import { useStreamContext } from "@/providers/Stream";
import {
  AIMessage,
  type BaseMessage,
  isAIMessage,
  isToolMessage,
  type MessageContentComplex,
} from "@langchain/core/messages";
import { useMessageMetadata } from "@langchain/react";
import { getContentString } from "../utils";
import { CommandBar } from "./shared";
import { MarkdownText } from "../markdown-text";
import { LoadExternalComponent } from "@langchain/langgraph-sdk/react-ui";
import { cn } from "@/lib/utils";
import { ToolCalls, ToolResult } from "./tool-calls";
import { Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { isAgentInboxInterruptSchema } from "@/lib/agent-inbox-interrupt";
import { ThreadView } from "../agent-inbox";
import { prettifyText } from "../agent-inbox/utils";
import { useQueryState, parseAsBoolean } from "nuqs";
import { GenericInterruptView } from "./generic-interrupt";
import { useArtifact } from "../artifact";
import { MessageTimestamp } from "./timestamp";
import { getKnownStreamErrorInfo } from "@/lib/stream-errors";
import { AlertTriangle } from "lucide-react";

function CustomComponent({
  message,
  thread,
}: {
  message: BaseMessage;
  thread: ReturnType<typeof useStreamContext>;
}) {
  const artifact = useArtifact();
  const { values } = useStreamContext();
  const customComponents = values.ui?.filter(
    (ui) => ui.metadata?.message_id === message.id,
  );

  if (!customComponents?.length) return null;
  return (
    <Fragment key={message.id}>
      {customComponents.map((customComponent) => (
        <LoadExternalComponent
          key={customComponent.id}
          stream={thread as never}
          message={customComponent}
          meta={{ ui: customComponent, artifact }}
        />
      ))}
    </Fragment>
  );
}

function parseAnthropicStreamedToolCalls(
  content: MessageContentComplex[],
): AIMessage["tool_calls"] {
  const toolCallContents = content.filter((c) => c.type === "tool_use" && c.id);

  return toolCallContents.map((tc) => {
    const toolCall = tc as Record<string, any>;
    let json: Record<string, any> = {};
    if (toolCall?.input) {
      try {
        json = parsePartialJson(toolCall.input) ?? {};
      } catch {
        // Pass
      }
    }
    return {
      name: toolCall.name ?? "",
      id: toolCall.id ?? "",
      args: json,
      type: "tool_call",
    };
  });
}

interface InterruptProps {
  interrupt?: unknown;
  isLastMessage: boolean;
  hasNoAIOrToolMessages: boolean;
}

function Interrupt({
  interrupt,
  isLastMessage,
  hasNoAIOrToolMessages,
}: InterruptProps) {
  const fallbackValue = Array.isArray(interrupt)
    ? (interrupt as Record<string, any>[])
    : (((interrupt as { value?: unknown } | undefined)?.value ??
        interrupt) as Record<string, any>);

  return (
    <>
      {isAgentInboxInterruptSchema(interrupt) &&
        (isLastMessage || hasNoAIOrToolMessages) && (
          <ThreadView interrupt={interrupt} />
        )}
      {interrupt &&
      !isAgentInboxInterruptSchema(interrupt) &&
      (isLastMessage || hasNoAIOrToolMessages) ? (
        <GenericInterruptView interrupt={fallbackValue} />
      ) : null}
    </>
  );
}

function parseToolContent(content: unknown): unknown {
  if (typeof content !== "string") return content;

  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

function getStringField(value: unknown, field: string): string | undefined {
  if (!value || typeof value !== "object") return undefined;

  const record = value as Record<string, unknown>;
  const fieldValue = record[field];
  return typeof fieldValue === "string" && fieldValue.trim()
    ? fieldValue
    : undefined;
}

function getToolFallbackMarkdown(message: BaseMessage): string {
  const toolName =
    typeof (message as { name?: unknown }).name === "string"
      ? ((message as { name?: string }).name ?? "")
      : "";
  const toolLabel = toolName ? prettifyText(toolName) : "工具";
  const parsedContent = parseToolContent(message.content);
  const error = getStringField(parsedContent, "error");

  if (toolName === "generate_image") {
    const markdown = getStringField(parsedContent, "markdown");
    const imageUrl = getStringField(parsedContent, "image_url");

    if (markdown) return `图片生成结果如下：\n\n${markdown}`;
    if (imageUrl) return `图片生成结果如下：\n\n![生成图片](${imageUrl})`;
    if (error) return `图片生成没有完成。\n\n原因：${error}`;

    return "图片生成已执行，但服务没有返回可展示的图片。";
  }

  if (error) return `${toolLabel}没有完成。\n\n原因：${error}`;

  const payload =
    typeof parsedContent === "string"
      ? parsedContent
      : (JSON.stringify(parsedContent, null, 2) ?? "无返回内容");

  return `${toolLabel}已执行完成，但没有生成后续回答。下面是工具返回结果：\n\n\`\`\`json\n${payload}\n\`\`\``;
}

function HiddenToolResultFallback({ message }: { message: BaseMessage }) {
  const thread = useStreamContext();
  const meta = useMessageMetadata(thread, message.id);

  return (
    <div className="group mr-auto flex w-full items-start gap-2">
      <div className="flex w-full flex-col gap-2">
        <div className="py-1">
          <MarkdownText>{getToolFallbackMarkdown(message)}</MarkdownText>
        </div>
        <MessageTimestamp
          message={message}
          metadata={meta}
          align="left"
        />
      </div>
    </div>
  );
}

function getLoadingText(elapsedSeconds: number) {
  if (elapsedSeconds >= 45) {
    return "大模型仍在处理，可能正在等待工具或外部服务返回结果…";
  }

  if (elapsedSeconds >= 15) {
    return "大模型仍在运作中，请再稍候…";
  }

  if (elapsedSeconds >= 6) {
    return "正在调用模型或工具，请稍候…";
  }

  return "正在思考…";
}

export function AssistantMessage({
  message,
  isLoading,
  handleRegenerate,
}: {
  message: BaseMessage | undefined;
  isLoading: boolean;
  handleRegenerate: (parentCheckpointId: string | undefined) => void;
}) {
  const content = message?.content ?? [];
  const contentString = getContentString(content);
  const [hideToolCalls] = useQueryState(
    "hideToolCalls",
    parseAsBoolean.withDefault(true),
  );

  const thread = useStreamContext();
  const isLastMessage =
    thread.messages[thread.messages.length - 1].id === message?.id;
  const hasNoAIOrToolMessages = !thread.messages.find(
    (m) => m.type === "ai" || m.type === "tool",
  );
  const meta = useMessageMetadata(thread, message?.id);
  const threadInterrupt = thread.interrupt;

  const parentCheckpointId = meta?.parentCheckpointId;
  const anthropicStreamedToolCalls = Array.isArray(content)
    ? parseAnthropicStreamedToolCalls(content)
    : undefined;

  const hasToolCalls =
    message &&
    isAIMessage(message) &&
    message.tool_calls &&
    message.tool_calls.length > 0;
  const toolCallsHaveContents =
    hasToolCalls &&
    message.tool_calls?.some(
      (tc) => tc.args && Object.keys(tc.args).length > 0,
    );
  const hasAnthropicToolCalls = !!anthropicStreamedToolCalls?.length;
  const isToolResult = !!message && isToolMessage(message);
  const messageIndex = message
    ? thread.messages.findIndex((item) => item.id === message.id)
    : -1;
  const hasLaterAssistantContent =
    messageIndex >= 0 &&
    thread.messages
      .slice(messageIndex + 1)
      .some(
        (item) =>
          item.type === "ai" &&
          getContentString(item.content).trim().length > 0,
      );
  const shouldShowInterrupt =
    !!threadInterrupt && (isLastMessage || hasNoAIOrToolMessages);
  const isPendingApproval = isAgentInboxInterruptSchema(threadInterrupt);

  if (isToolResult && hideToolCalls) {
    if (!isLoading && !hasLaterAssistantContent) {
      return <HiddenToolResultFallback message={message} />;
    }

    return null;
  }

  return (
    <div className="group mr-auto flex w-full items-start gap-2">
      <div className="flex w-full flex-col gap-2">
        {isToolResult ? (
          <>
            <ToolResult message={message} />
            <Interrupt
              interrupt={threadInterrupt}
              isLastMessage={isLastMessage}
              hasNoAIOrToolMessages={hasNoAIOrToolMessages}
            />
          </>
        ) : (
          <>
            {contentString.length > 0 && (
              <div className="py-1">
                <MarkdownText>{contentString}</MarkdownText>
              </div>
            )}

            <Interrupt
              interrupt={threadInterrupt}
              isLastMessage={isLastMessage}
              hasNoAIOrToolMessages={hasNoAIOrToolMessages}
            />

            {!hideToolCalls && (
              <>
                {(hasToolCalls && toolCallsHaveContents && (
                  <ToolCalls
                    toolCalls={message.tool_calls}
                    waitingForApproval={
                      shouldShowInterrupt && isPendingApproval
                    }
                  />
                )) ||
                  (hasAnthropicToolCalls && (
                    <ToolCalls
                      toolCalls={anthropicStreamedToolCalls}
                      waitingForApproval={
                        shouldShowInterrupt && isPendingApproval
                      }
                    />
                  )) ||
                  (hasToolCalls && (
                    <ToolCalls
                      toolCalls={message.tool_calls}
                      waitingForApproval={
                        shouldShowInterrupt && isPendingApproval
                      }
                    />
                  ))}
              </>
            )}

            {message && (
              <CustomComponent
                message={message}
                thread={thread}
              />
            )}
            {message && (
              <MessageTimestamp
                message={message}
                metadata={meta}
                align="left"
              />
            )}
            <div
              className={cn(
                "mr-auto flex items-center gap-2 transition-opacity",
                "opacity-0 group-focus-within:opacity-100 group-hover:opacity-100",
              )}
            >
              <CommandBar
                content={contentString}
                isLoading={isLoading}
                isAiMessage={true}
                handleRegenerate={() => handleRegenerate(parentCheckpointId)}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function AssistantMessageFailure({ error }: { error: unknown }) {
  const knownError = getKnownStreamErrorInfo(error);

  return (
    <div className="group mr-auto flex w-full items-start gap-2">
      <div className="border-destructive/20 bg-destructive/5 text-destructive flex max-w-[min(80vw,42rem)] flex-col gap-1 rounded-2xl border px-4 py-3 text-sm">
        <div className="flex items-center gap-2 font-medium">
          <AlertTriangle className="size-4 shrink-0" />
          <span>{knownError?.title ?? "回答失败了"}</span>
        </div>
        <p className="text-destructive/80 leading-6">
          {knownError?.description ??
            "这次请求没有生成回答，请稍后重试，或重新发送这条消息。"}
        </p>
      </div>
    </div>
  );
}

export function AssistantMessageLoading() {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => window.clearInterval(timer);
  }, []);

  const loadingText = getLoadingText(elapsedSeconds);

  return (
    <div className="mr-auto flex items-start gap-2">
      <div className="bg-muted text-muted-foreground flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl px-4 py-2 text-sm">
        <span
          className="flex shrink-0 items-center gap-1"
          aria-hidden="true"
        >
          <span className="bg-foreground/50 h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_infinite] rounded-full" />
          <span className="bg-foreground/50 h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_0.5s_infinite] rounded-full" />
          <span className="bg-foreground/50 h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_1s_infinite] rounded-full" />
        </span>
        <span>{loadingText}</span>
        {elapsedSeconds >= 10 && (
          <span className="text-muted-foreground/80 text-xs">
            已等待 {elapsedSeconds} 秒
          </span>
        )}
      </div>
    </div>
  );
}
