import type { Thread } from "@langchain/langgraph-sdk";

import { getContentString } from "@/components/thread/utils";

function normalizedTitle(rawTitle: string): string | null {
  const title = rawTitle.trim();
  if (!title) return null;

  const serializedTextBlock = title.match(/["']text["']\s*:\s*["']([^"']+)/);
  if (serializedTextBlock?.[1]?.trim()) {
    return serializedTextBlock[1].trim();
  }

  return title;
}

export function getCustomThreadTitle(thread: Thread): string | null {
  const metadata = thread.metadata;
  if (!metadata || typeof metadata !== "object") return null;

  const title = (metadata as Record<string, unknown>).title;
  return typeof title === "string" ? normalizedTitle(title) : null;
}

export function getThreadTitle(thread: Thread): string {
  const customTitle = getCustomThreadTitle(thread);
  if (customTitle) return customTitle;

  if (
    typeof thread.values === "object" &&
    thread.values &&
    "messages" in thread.values &&
    Array.isArray(thread.values.messages) &&
    thread.values.messages.length > 0
  ) {
    const firstMessage = thread.values.messages[0];
    const title = getContentString(firstMessage.content).trim();
    if (title) return title;
  }

  return thread.thread_id;
}
