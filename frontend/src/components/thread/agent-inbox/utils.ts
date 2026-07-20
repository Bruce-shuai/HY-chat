import { BaseMessage, isBaseMessage } from "@langchain/core/messages";
import { format } from "date-fns";
import { startCase } from "lodash";
import {
  Action,
  Decision,
  DecisionWithEdits,
  HITLRequest,
  SubmitType,
} from "./types";

const TEXT_LABELS: Record<string, string> = {
  action_name: "操作名称",
  action_requests: "操作请求",
  additional_kwargs: "附加参数",
  allowed_decisions: "允许的处理方式",
  approve: "批准",
  args: "参数",
  assistant: "助手",
  content: "内容",
  description: "说明",
  edit: "编辑",
  generate_image: "生成图片",
  get_stock_quote: "股票行情",
  id: "编号",
  image_url: "图片链接",
  input: "输入",
  matches: "匹配结果",
  markdown: "图片预览",
  maxresults: "最多返回几条搜索结果",
  max_results: "最多返回几条搜索结果",
  messages: "消息",
  metadata: "元数据",
  model: "模型",
  name: "名称",
  output: "输出",
  prompt: "图片描述",
  provider: "服务",
  query: "查询内容",
  reason: "原因",
  reject: "拒绝",
  result: "结果",
  review_configs: "审核配置",
  role: "角色",
  search_workspace_code: "搜索工作区代码",
  size: "图片尺寸",
  state: "状态",
  status: "状态",
  system: "系统",
  tool: "工具",
  tool_calls: "工具调用",
  type: "类型",
  user: "用户",
  web_search: "网页搜索",
};

const AUTO_APPROVE_TOOLS_STORAGE_KEY = "hy-chat:auto-approve-tools";
const AUTO_APPROVAL_SUPPORTED_TOOLS = new Set(["web_search", "generate_image"]);

export function prettifyText(action: string) {
  const normalized = action
    .trim()
    .replace(/[\s-]+/g, "_")
    .toLowerCase();
  return TEXT_LABELS[normalized] ?? startCase(action.replace(/_/g, " "));
}

function normalizeToolName(toolName: string): string {
  return toolName.trim().toLowerCase();
}

function readAutoApprovedToolSet(): Set<string> {
  if (typeof window === "undefined") {
    return new Set();
  }

  try {
    const raw = window.localStorage.getItem(AUTO_APPROVE_TOOLS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];

    if (!Array.isArray(parsed)) {
      return new Set();
    }

    return new Set(
      parsed
        .filter((item): item is string => typeof item === "string")
        .map(normalizeToolName)
        .filter((toolName) => AUTO_APPROVAL_SUPPORTED_TOOLS.has(toolName)),
    );
  } catch (error) {
    console.error("Failed to read auto-approved tools", error);
    return new Set();
  }
}

export function isToolAutoApprovalSupported(toolName?: string): boolean {
  if (!toolName) return false;
  return AUTO_APPROVAL_SUPPORTED_TOOLS.has(normalizeToolName(toolName));
}

export function isToolAutoApproved(toolName?: string): boolean {
  if (!toolName || !isToolAutoApprovalSupported(toolName)) {
    return false;
  }

  return readAutoApprovedToolSet().has(normalizeToolName(toolName));
}

export function setToolAutoApproved(toolName: string, enabled: boolean) {
  if (!isToolAutoApprovalSupported(toolName) || typeof window === "undefined") {
    return;
  }

  const normalizedToolName = normalizeToolName(toolName);
  const approvedTools = readAutoApprovedToolSet();

  if (enabled) {
    approvedTools.add(normalizedToolName);
  } else {
    approvedTools.delete(normalizedToolName);
  }

  try {
    window.localStorage.setItem(
      AUTO_APPROVE_TOOLS_STORAGE_KEY,
      JSON.stringify([...approvedTools]),
    );
  } catch (error) {
    console.error("Failed to save auto-approved tools", error);
  }
}

export function isArrayOfMessages(
  value: Record<string, any>[],
): value is BaseMessage[] {
  if (
    value.every(isBaseMessage) ||
    (Array.isArray(value) &&
      value.every(
        (v) =>
          typeof v === "object" &&
          "id" in v &&
          "type" in v &&
          "content" in v &&
          "additional_kwargs" in v,
      ))
  ) {
    return true;
  }
  return false;
}

export function baseMessageObject(item: unknown): string {
  if (isBaseMessage(item)) {
    const contentText =
      typeof item.content === "string"
        ? item.content
        : JSON.stringify(item.content, null);
    let toolCallText = "";
    if ("tool_calls" in item) {
      toolCallText = JSON.stringify(item.tool_calls, null);
    }
    if ("type" in item) {
      return `${prettifyText(String(item.type))}:${contentText ? ` ${contentText}` : ""}${toolCallText ? ` - 工具调用: ${toolCallText}` : ""}`;
    } else if ("getType" in item) {
      return `${prettifyText((item as BaseMessage).getType())}:${contentText ? ` ${contentText}` : ""}${toolCallText ? ` - 工具调用: ${toolCallText}` : ""}`;
    }
  } else if (
    typeof item === "object" &&
    item &&
    "type" in item &&
    "content" in item
  ) {
    const contentText =
      typeof item.content === "string"
        ? item.content
        : JSON.stringify(item.content, null);
    let toolCallText = "";
    if ("tool_calls" in item) {
      toolCallText = JSON.stringify(item.tool_calls, null);
    }
    return `${prettifyText(String(item.type))}:${contentText ? ` ${contentText}` : ""}${toolCallText ? ` - 工具调用: ${toolCallText}` : ""}`;
  }

  if (typeof item === "object") {
    return JSON.stringify(item, null);
  } else {
    return item as string;
  }
}

export function unknownToPrettyDate(input: unknown): string | undefined {
  try {
    if (
      Object.prototype.toString.call(input) === "[object Date]" ||
      new Date(input as string)
    ) {
      return format(new Date(input as string), "yyyy/MM/dd HH:mm");
    }
  } catch {
    // failed to parse date. no-op
  }
  return undefined;
}

export function createDefaultHumanResponse(
  hitlRequest: HITLRequest,
  initialHumanInterruptEditValue: React.MutableRefObject<
    Record<string, string>
  >,
): {
  responses: DecisionWithEdits[];
  defaultSubmitType: SubmitType | undefined;
  hasApprove: boolean;
} {
  const responses: DecisionWithEdits[] = [];
  const actionRequest = hitlRequest.action_requests?.[0];
  const reviewConfig =
    hitlRequest.review_configs?.find(
      (config) => config.action_name === actionRequest?.name,
    ) ?? hitlRequest.review_configs?.[0];

  if (!actionRequest || !reviewConfig) {
    return { responses: [], defaultSubmitType: undefined, hasApprove: false };
  }

  const allowedDecisions = reviewConfig.allowed_decisions ?? [];

  if (allowedDecisions.includes("edit")) {
    Object.entries(actionRequest.args).forEach(([key, value]) => {
      const stringValue =
        typeof value === "string" || typeof value === "number"
          ? value.toString()
          : JSON.stringify(value, null);
      initialHumanInterruptEditValue.current = {
        ...initialHumanInterruptEditValue.current,
        [key]: stringValue,
      };
    });

    const editedAction: Action = {
      name: actionRequest.name,
      args: { ...actionRequest.args },
    };

    responses.push({
      type: "edit",
      edited_action: editedAction,
      acceptAllowed: allowedDecisions.includes("approve"),
      editsMade: false,
    });
  }

  if (allowedDecisions.includes("approve")) {
    responses.push({ type: "approve" });
  }

  if (allowedDecisions.includes("reject")) {
    responses.push({ type: "reject", message: "" });
  }

  // Determine default submit type. Priority: approve > reject > edit
  let defaultSubmitType: SubmitType | undefined;

  if (allowedDecisions.includes("approve")) {
    defaultSubmitType = "approve";
  } else if (allowedDecisions.includes("reject")) {
    defaultSubmitType = "reject";
  } else if (allowedDecisions.includes("edit")) {
    defaultSubmitType = "edit";
  }

  const hasApprove = allowedDecisions.includes("approve");

  return { responses, defaultSubmitType, hasApprove };
}

export function buildDecisionFromState(
  responses: DecisionWithEdits[],
  selectedSubmitType: SubmitType | undefined,
): { decision?: Decision; error?: string } {
  if (!responses.length) {
    return { error: "请先选择一种处理方式。" };
  }

  const selectedDecision = responses.find(
    (response) => response.type === selectedSubmitType,
  );

  if (!selectedDecision) {
    return { error: "还没有选择处理方式。" };
  }

  if (selectedDecision.type === "approve") {
    return { decision: { type: "approve" } };
  }

  if (selectedDecision.type === "reject") {
    const message = selectedDecision.message?.trim();
    if (!message) {
      return { error: "请填写拒绝原因。" };
    }
    return { decision: { type: "reject", message } };
  }

  if (selectedDecision.type === "edit") {
    if (selectedDecision.acceptAllowed && !selectedDecision.editsMade) {
      return { decision: { type: "approve" } };
    }

    return {
      decision: {
        type: "edit",
        edited_action: selectedDecision.edited_action,
      },
    };
  }

  return { error: "暂不支持这种处理方式。" };
}

export function constructOpenInStudioURL(
  deploymentUrl: string,
  threadId?: string,
) {
  const smithStudioURL = new URL("https://smith.langchain.com/studio/thread");
  // trim the trailing slash from deploymentUrl
  const trimmedDeploymentUrl = deploymentUrl.replace(/\/$/, "");

  if (threadId) {
    smithStudioURL.pathname += `/${threadId}`;
  }

  smithStudioURL.searchParams.append("baseUrl", trimmedDeploymentUrl);

  return smithStudioURL.toString();
}

export function haveArgsChanged(
  args: unknown,
  initialValues: Record<string, string>,
): boolean {
  if (typeof args !== "object" || !args) {
    return false;
  }

  const currentValues = args as Record<string, string>;

  return Object.entries(currentValues).some(([key, value]) => {
    const valueString = ["string", "number"].includes(typeof value)
      ? value.toString()
      : JSON.stringify(value, null);
    return initialValues[key] !== valueString;
  });
}
