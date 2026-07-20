import { AIMessage, ToolMessage } from "@langchain/core/messages";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp } from "lucide-react";
import { prettifyText } from "../agent-inbox/utils";

function isComplexValue(value: any): boolean {
  return Array.isArray(value) || (typeof value === "object" && value !== null);
}

function formatToolValue(key: string, value: any): string {
  const normalizedKey = key
    .trim()
    .replace(/[\s-]+/g, "_")
    .toLowerCase();

  if (normalizedKey === "max_results" && typeof value !== "object") {
    return `${value} 条`;
  }

  return String(value);
}

export function ToolCalls({
  toolCalls,
  waitingForApproval = false,
}: {
  toolCalls: AIMessage["tool_calls"];
  waitingForApproval?: boolean;
}) {
  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <div className="mx-auto grid max-w-3xl grid-rows-[1fr_auto] gap-2">
      {waitingForApproval && (
        <p className="text-muted-foreground bg-muted/30 rounded-lg border px-3 py-2 text-sm">
          这个工具调用正在等待人工确认。请在上方审批面板点击“批准”，HY-chat
          才会执行工具并继续回答。
        </p>
      )}
      {toolCalls.map((tc, idx) => {
        const args = tc.args as Record<string, any>;
        const hasArgs = Object.keys(args).length > 0;
        return (
          <div
            key={idx}
            className="border-border overflow-hidden rounded-lg border"
          >
            <div className="border-border bg-muted/30 border-b px-4 py-2">
              <h3 className="text-foreground font-medium">
                {prettifyText(tc.name)}
                {tc.id && (
                  <span className="text-muted-foreground ml-2 inline-flex items-center gap-1 text-xs font-normal">
                    调用编号：
                    <code className="bg-muted rounded px-2 py-1 text-sm">
                      {tc.id}
                    </code>
                  </span>
                )}
              </h3>
            </div>
            {hasArgs ? (
              <table className="min-w-full divide-y divide-gray-200">
                <tbody className="divide-y divide-gray-200">
                  {Object.entries(args).map(([key, value], argIdx) => (
                    <tr key={argIdx}>
                      <td className="text-foreground px-4 py-2 text-sm font-medium whitespace-nowrap">
                        {prettifyText(key)}
                      </td>
                      <td className="text-muted-foreground px-4 py-2 text-sm">
                        {isComplexValue(value) ? (
                          <code className="bg-muted/30 rounded px-2 py-1 font-mono text-sm break-all">
                            {JSON.stringify(value, null, 2)}
                          </code>
                        ) : (
                          formatToolValue(key, value)
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <code className="block p-3 text-sm">{"{}"}</code>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ToolResult({ message }: { message: ToolMessage }) {
  const [isExpanded, setIsExpanded] = useState(false);

  let parsedContent: any;

  try {
    if (typeof message.content === "string") {
      parsedContent = JSON.parse(message.content);
    } else {
      parsedContent = message.content;
    }
  } catch {
    parsedContent = message.content;
  }

  const isJsonContent = isComplexValue(parsedContent);
  const contentStr = isJsonContent
    ? JSON.stringify(parsedContent, null, 2)
    : String(message.content);
  const contentLines = contentStr.split("\n");
  const shouldTruncate = contentLines.length > 4 || contentStr.length > 500;
  const displayedContent =
    shouldTruncate && !isExpanded
      ? contentStr.length > 500
        ? contentStr.slice(0, 500) + "..."
        : contentLines.slice(0, 4).join("\n") + "\n..."
      : contentStr;

  return (
    <div className="mx-auto grid max-w-3xl grid-rows-[1fr_auto] gap-2">
      <div className="border-border overflow-hidden rounded-lg border">
        <div className="border-border bg-muted/30 border-b px-4 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            {message.name ? (
              <h3 className="text-foreground font-medium">
                工具结果：{" "}
                <code className="bg-muted rounded px-2 py-1">
                  {prettifyText(message.name)}
                </code>
              </h3>
            ) : (
              <h3 className="text-foreground font-medium">工具结果</h3>
            )}
            {message.tool_call_id && (
              <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                调用编号：
                <code className="bg-muted rounded px-2 py-1 text-sm">
                  {message.tool_call_id}
                </code>
              </span>
            )}
          </div>
        </div>
        <motion.div
          className="bg-muted min-w-full"
          initial={false}
          animate={{ height: "auto" }}
          transition={{ duration: 0.3 }}
        >
          <div className="p-3">
            <AnimatePresence
              mode="wait"
              initial={false}
            >
              <motion.div
                key={isExpanded ? "expanded" : "collapsed"}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.2 }}
              >
                {isJsonContent ? (
                  <table className="min-w-full divide-y divide-gray-200">
                    <tbody className="divide-y divide-gray-200">
                      {(Array.isArray(parsedContent)
                        ? isExpanded
                          ? parsedContent
                          : parsedContent.slice(0, 5)
                        : Object.entries(parsedContent)
                      ).map((item, argIdx) => {
                        const [key, value] = Array.isArray(parsedContent)
                          ? [argIdx, item]
                          : [item[0], item[1]];
                        return (
                          <tr key={argIdx}>
                            <td className="text-foreground px-4 py-2 text-sm font-medium whitespace-nowrap">
                              {prettifyText(String(key))}
                            </td>
                            <td className="text-muted-foreground px-4 py-2 text-sm">
                              {isComplexValue(value) ? (
                                <code className="bg-muted/30 rounded px-2 py-1 font-mono text-sm break-all">
                                  {JSON.stringify(value, null, 2)}
                                </code>
                              ) : (
                                formatToolValue(String(key), value)
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                ) : (
                  <code className="block text-sm">{displayedContent}</code>
                )}
              </motion.div>
            </AnimatePresence>
          </div>
          {((shouldTruncate && !isJsonContent) ||
            (isJsonContent &&
              Array.isArray(parsedContent) &&
              parsedContent.length > 5)) && (
            <motion.button
              onClick={() => setIsExpanded(!isExpanded)}
              className="border-border text-muted-foreground hover:bg-muted/30 hover:text-muted-foreground flex w-full cursor-pointer items-center justify-center border-t-[1px] py-2 transition-all duration-200 ease-in-out"
              initial={{ scale: 1 }}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              {isExpanded ? <ChevronUp /> : <ChevronDown />}
            </motion.button>
          )}
        </motion.div>
      </div>
    </div>
  );
}
