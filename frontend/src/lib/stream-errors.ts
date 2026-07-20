import { appendAdminContact } from "./admin-contact";

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  if (
    typeof error === "object" &&
    error &&
    "message" in error &&
    typeof error.message === "string"
  ) {
    return error.message;
  }

  return String(error);
}

function collectErrorText(
  error: unknown,
  seen = new WeakSet<object>(),
): string {
  if (error == null) return "";
  if (typeof error === "string") return error;
  if (typeof error === "number" || typeof error === "boolean") {
    return String(error);
  }
  if (error instanceof Error) {
    return [error.name, error.message, collectErrorText(error.cause, seen)]
      .filter(Boolean)
      .join(" ");
  }
  if (typeof error !== "object") return String(error);
  if (seen.has(error)) return "";
  seen.add(error);

  return Object.entries(error as Record<string, unknown>)
    .flatMap(([key, value]) => [key, collectErrorText(value, seen)])
    .filter(Boolean)
    .join(" ");
}

export function isAlreadyConsumedInterruptError(error: unknown): boolean {
  const message = getErrorMessage(error).toLowerCase();
  return message.includes("already-consumed interrupt");
}

export function isTransientInterruptResumeError(error: unknown): boolean {
  const message = getErrorMessage(error).toLowerCase();
  return (
    message.includes("interrupt_lookup_failed") ||
    (message.includes("thread with id") && message.includes("not found")) ||
    (message.includes("404") && message.includes("not found"))
  );
}

export type KnownStreamErrorInfo = {
  title: string;
  description: string;
  kind:
    "rate-limit" | "high-cost-tool" | "model-permission" | "quota" | "network";
};

export function getKnownStreamErrorInfo(
  error: unknown,
): KnownStreamErrorInfo | null {
  const message = getErrorMessage(error);
  const searchText = [message, collectErrorText(error)]
    .filter(Boolean)
    .join(" ");
  const normalized = searchText
    .replaceAll("generate_image", "生成图片")
    .replaceAll("web_search", "网页搜索")
    .replaceAll("get_stock_quote", "股票行情");

  const policyMessage = normalized.match(
    /(已被高成本工具权限拦截[^"'\\\n)]*|当前账号[^"'\\\n)]+|本月标记配额已用尽|请求过于频繁[^"'\\\n)]*)/,
  )?.[0];
  if (policyMessage?.startsWith("请求过于频繁")) {
    return {
      kind: "rate-limit",
      title: "发送太频繁了",
      description: `${policyMessage}。请稍等一分钟后再继续发送。`,
    };
  }
  if (/(\b429\b|too many requests|rate.?limit|rpm|每分钟)/i.test(normalized)) {
    return {
      kind: "rate-limit",
      title: "发送太频繁了",
      description: "已达到每分钟请求上限，请稍等一分钟后再继续发送。",
    };
  }
  if (policyMessage?.includes("高成本工具权限拦截")) {
    return {
      kind: "high-cost-tool",
      title: "高成本工具已被拦截",
      description: appendAdminContact(policyMessage),
    };
  }
  if (policyMessage?.startsWith("当前账号")) {
    return {
      kind: "model-permission",
      title: "当前账号没有权限",
      description: appendAdminContact(policyMessage),
    };
  }
  if (policyMessage?.includes("本月标记配额已用尽")) {
    return {
      kind: "quota",
      title: "本月额度已用尽",
      description: appendAdminContact(policyMessage),
    };
  }

  if (/failed to fetch/i.test(message)) {
    return {
      kind: "network",
      title: "无法连接后端服务",
      description: "请确认服务正在运行后再试。",
    };
  }

  return null;
}
