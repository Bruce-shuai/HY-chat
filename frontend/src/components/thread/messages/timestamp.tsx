import type { BaseMessage } from "@langchain/core/messages";

import { cn } from "@/lib/utils";
import { getContentString } from "../utils";

const fallbackMessageTimes = new Map<string, number>();

type MessageTimestampProps = {
  message: BaseMessage;
  metadata?: unknown;
  align: "left" | "right";
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object";
}

function readDate(value: unknown): Date | null {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value;
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    const millis = value < 1_000_000_000_000 ? value * 1000 : value;
    const date = new Date(millis);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;

  if (/^\d+$/.test(trimmed)) {
    return readDate(Number(trimmed));
  }

  const date = new Date(trimmed);
  return Number.isNaN(date.getTime()) ? null : date;
}

function readDateFromRecord(record: Record<string, unknown>): Date | null {
  for (const key of [
    "created_at",
    "createdAt",
    "updated_at",
    "updatedAt",
    "send_time",
    "sendTime",
    "timestamp",
    "time",
  ]) {
    const date = readDate(record[key]);
    if (date) return date;
  }

  for (const key of ["metadata", "additional_kwargs", "response_metadata"]) {
    const nested = record[key];
    if (isRecord(nested)) {
      const date = readDateFromRecord(nested);
      if (date) return date;
    }
  }

  return null;
}

function fallbackDateForMessage(message: BaseMessage) {
  const key = [
    message.id,
    message.type,
    getContentString(message.content).slice(0, 120),
  ]
    .filter(Boolean)
    .join(":");
  const stableKey = key || "unknown-message";
  const existing = fallbackMessageTimes.get(stableKey);
  if (existing) return new Date(existing);

  const now = Date.now();
  fallbackMessageTimes.set(stableKey, now);
  return new Date(now);
}

function resolveMessageDate(message: BaseMessage, metadata?: unknown) {
  if (isRecord(metadata)) {
    const date = readDateFromRecord(metadata);
    if (date) return date;
  }

  if (isRecord(message)) {
    const date = readDateFromRecord(message);
    if (date) return date;
  }

  return fallbackDateForMessage(message);
}

function sameDate(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function formatMessageTime(date: Date) {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const time = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);

  if (sameDate(date, now)) return `今天 ${time}`;
  if (sameDate(date, yesterday)) return `昨天 ${time}`;

  const dateText = new Intl.DateTimeFormat("zh-CN", {
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);

  return `${dateText} ${time}`;
}

export function MessageTimestamp({
  message,
  metadata,
  align,
}: MessageTimestampProps) {
  const label = formatMessageTime(resolveMessageDate(message, metadata));

  return (
    <div
      className={cn(
        "text-muted-foreground/70 text-xs leading-none opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100",
        align === "right" ? "text-right" : "text-left",
      )}
      title={label}
    >
      {label}
    </div>
  );
}
