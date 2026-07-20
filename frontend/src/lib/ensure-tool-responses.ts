import { v4 as uuidv4 } from "uuid";
import {
  type BaseMessage,
  isAIMessage,
  isToolMessage,
  ToolMessage,
} from "@langchain/core/messages";

export const DO_NOT_RENDER_ID_PREFIX = "do-not-render-";

export function ensureToolCallsHaveResponses(
  messages: BaseMessage[],
): ToolMessage[] {
  const newMessages: ToolMessage[] = [];

  messages.forEach((message, index) => {
    if (!isAIMessage(message) || message.tool_calls?.length === 0) {
      // If it's not an AI message, or it doesn't have tool calls, we can ignore.
      return;
    }
    // If it has tool calls, ensure the message which follows this is a tool message
    const followingMessage = messages[index + 1];
    if (followingMessage && isToolMessage(followingMessage)) {
      // Following message is a tool message, so we can ignore.
      return;
    }

    // Since the following message is not a tool message, we must create a new tool message
    newMessages.push(
      ...(message.tool_calls?.map(
        (tc) =>
          new ToolMessage({
            tool_call_id: tc.id ?? "",
            id: `${DO_NOT_RENDER_ID_PREFIX}${uuidv4()}`,
            name: tc.name,
            content: "工具调用已处理。",
          }),
      ) ?? []),
    );
  });

  return newMessages;
}
