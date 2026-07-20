import { useCallback, useEffect, useMemo, useState } from "react";
import type { BaseMessage } from "@langchain/core/messages";

import { getContentString } from "../utils";

type UseThreadMessageStateArgs = {
  threadId: string | null;
  streamThreadId: string | null;
  isStreamThreadLoading: boolean;
  messages: BaseMessage[];
  hasInterrupt: boolean;
};

function hasVisibleAssistantContent(message: BaseMessage | undefined) {
  return (
    message?.type === "ai" &&
    getContentString(message.content).trim().length > 0
  );
}

export function useThreadMessageState({
  threadId,
  streamThreadId,
  isStreamThreadLoading,
  messages,
  hasInterrupt,
}: UseThreadMessageStateArgs) {
  const [firstTokenReceived, setFirstTokenReceived] = useState(false);
  const isThreadLoading =
    isStreamThreadLoading || (threadId ?? null) !== (streamThreadId ?? null);
  const visibleMessages = useMemo(
    () => (isThreadLoading ? [] : messages),
    [isThreadLoading, messages],
  );

  useEffect(() => {
    if (isThreadLoading) return;
    if (hasVisibleAssistantContent(messages[messages.length - 1])) {
      setFirstTokenReceived(true);
    }
  }, [isThreadLoading, messages]);

  useEffect(() => {
    setFirstTokenReceived(false);
  }, [threadId]);

  const waitForFirstToken = useCallback(() => {
    setFirstTokenReceived(false);
  }, []);

  const hasNoAIOrToolMessages = useMemo(
    () =>
      !visibleMessages.some(
        (message) => message.type === "ai" || message.type === "tool",
      ),
    [visibleMessages],
  );

  const chatStarted =
    isThreadLoading || Boolean(threadId) || visibleMessages.length > 0;
  const messageListResetKey = [
    threadId ?? "new-thread",
    streamThreadId ?? "pending",
    isThreadLoading ? "loading" : visibleMessages.length,
    hasInterrupt ? "interrupt" : "normal",
  ].join(":");

  return {
    chatStarted,
    firstTokenReceived,
    hasNoAIOrToolMessages,
    isThreadLoading,
    messageListResetKey,
    visibleMessages,
    waitForFirstToken,
  };
}
