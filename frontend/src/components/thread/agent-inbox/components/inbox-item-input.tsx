import React from "react";
import { DecisionWithEdits, SubmitType, HITLRequest } from "../types";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Check, Undo2, X } from "lucide-react";
import { MarkdownText } from "../../markdown-text";
import {
  haveArgsChanged,
  isToolAutoApprovalSupported,
  isToolAutoApproved,
  prettifyText,
  setToolAutoApproved,
} from "../utils";
import { toast } from "sonner";

type EditResponse = Extract<DecisionWithEdits, { type: "edit" }>;
type RejectResponse = Extract<DecisionWithEdits, { type: "reject" }>;

function stringifyArgValue(value: unknown): string {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value.toString();
  }

  if (value == null) {
    return "";
  }

  return JSON.stringify(value, null, 2);
}

function ResetButton({ handleReset }: { handleReset: () => void }) {
  return (
    <Button
      onClick={handleReset}
      variant="ghost"
      size="sm"
      className="text-muted-foreground flex items-center justify-center gap-2 hover:text-red-500"
    >
      <Undo2 className="h-4 w-4" />
      <span>重置</span>
    </Button>
  );
}

function ArgsRenderer({ args }: { args: Record<string, unknown> }) {
  return (
    <div className="flex w-full flex-col items-start gap-4">
      {Object.entries(args).map(([key, value]) => {
        const stringValue = stringifyArgValue(value);

        return (
          <div
            key={`args-${key}`}
            className="flex w-full flex-col items-start gap-1.5"
          >
            <p className="text-muted-foreground text-sm leading-[18px] text-wrap">
              {prettifyText(key)}
            </p>
            <div className="text-foreground w-full max-w-full overflow-hidden rounded-md bg-zinc-100 p-3 text-[13px] leading-[18px] break-words [overflow-wrap:anywhere]">
              <MarkdownText>{stringValue}</MarkdownText>
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface InboxItemInputProps {
  interruptValue: HITLRequest;
  humanResponse: DecisionWithEdits[];
  supportsMultipleMethods: boolean;
  approveAllowed: boolean;
  hasEdited: boolean;
  hasAddedResponse: boolean;
  initialValues: Record<string, string>;
  isLoading: boolean;
  selectedSubmitType: SubmitType | undefined;

  setHumanResponse: React.Dispatch<React.SetStateAction<DecisionWithEdits[]>>;
  setSelectedSubmitType: React.Dispatch<
    React.SetStateAction<SubmitType | undefined>
  >;
  setHasAddedResponse: React.Dispatch<React.SetStateAction<boolean>>;
  setHasEdited: React.Dispatch<React.SetStateAction<boolean>>;

  handleSubmit: (
    e: React.MouseEvent<HTMLButtonElement, MouseEvent> | React.KeyboardEvent,
    submitTypeOverride?: SubmitType,
  ) => Promise<void> | void;
}

export function InboxItemInput({
  interruptValue,
  humanResponse,
  approveAllowed,
  hasEdited,
  hasAddedResponse,
  initialValues,
  isLoading,
  supportsMultipleMethods,
  selectedSubmitType,
  setHumanResponse,
  setSelectedSubmitType,
  setHasAddedResponse,
  setHasEdited,
  handleSubmit,
}: InboxItemInputProps) {
  const allowedDecisions =
    interruptValue.review_configs?.[0]?.allowed_decisions ?? [];
  const actionRequest = interruptValue.action_requests?.[0];
  const actionName = actionRequest?.name;
  const actionArgs = actionRequest?.args ?? {};
  const isEditAllowed = allowedDecisions.includes("edit");
  const isRejectAllowed = allowedDecisions.includes("reject");
  const hasArgs = Object.keys(actionArgs).length > 0;
  const editResponse = humanResponse.find(
    (response): response is EditResponse => response.type === "edit",
  );
  const rejectResponse = humanResponse.find(
    (response): response is RejectResponse => response.type === "reject",
  );
  const [autoApproveEnabled, setAutoApproveEnabled] = React.useState(false);

  React.useEffect(() => {
    if (!actionName || !isToolAutoApprovalSupported(actionName)) {
      setAutoApproveEnabled(false);
      return;
    }

    setAutoApproveEnabled(isToolAutoApproved(actionName));
  }, [actionName]);

  const setDefaultSubmitType = () => {
    if (approveAllowed) {
      setSelectedSubmitType("approve");
      return;
    }

    if (isEditAllowed) {
      setSelectedSubmitType("edit");
      return;
    }

    if (isRejectAllowed) {
      setSelectedSubmitType("reject");
    }
  };

  const onEditChange = (
    change: string | string[],
    response: DecisionWithEdits,
    key: string | string[],
  ) => {
    if (
      (Array.isArray(change) && !Array.isArray(key)) ||
      (!Array.isArray(change) && Array.isArray(key))
    ) {
      toast.error("错误", {
        description: "无法更新编辑后的值。",
        richColors: true,
        closeButton: true,
      });
      return;
    }

    let valuesChanged = true;
    if (response.type === "edit" && response.edited_action) {
      const updatedArgs = { ...(response.edited_action.args || {}) };

      if (Array.isArray(change) && Array.isArray(key)) {
        change.forEach((value, index) => {
          if (index < key.length) {
            updatedArgs[key[index]] = value;
          }
        });
      } else {
        updatedArgs[key as string] = change as string;
      }

      valuesChanged = haveArgsChanged(updatedArgs, initialValues);
    }

    if (!valuesChanged) {
      setHasEdited(false);
      if (approveAllowed) {
        setSelectedSubmitType("approve");
      } else if (hasAddedResponse) {
        setSelectedSubmitType("reject");
      } else if (isEditAllowed) {
        setSelectedSubmitType("edit");
      }
    } else {
      setSelectedSubmitType("edit");
      setHasEdited(true);
    }

    setHumanResponse((prev) => {
      if (response.type !== "edit" || !response.edited_action) {
        console.error("Mismatched response type for edit", response.type);
        return prev;
      }

      const newArgs =
        Array.isArray(change) && Array.isArray(key)
          ? {
              ...response.edited_action.args,
              ...Object.fromEntries(key.map((k, index) => [k, change[index]])),
            }
          : {
              ...response.edited_action.args,
              [key as string]: change as string,
            };

      const newEdit: DecisionWithEdits = {
        type: "edit",
        edited_action: {
          name: response.edited_action.name,
          args: newArgs,
        },
      };

      return prev.map((existing) => {
        if (existing.type !== "edit") {
          return existing;
        }

        if (existing.acceptAllowed) {
          return {
            ...newEdit,
            acceptAllowed: true,
            editsMade: valuesChanged,
          };
        }

        return newEdit;
      });
    });
  };

  const onRejectChange = (change: string, response: DecisionWithEdits) => {
    if (response.type !== "reject") {
      console.error("Mismatched response type for rejection");
      return;
    }

    const trimmed = change.trim();
    setHasAddedResponse(!!trimmed);

    if (!trimmed) {
      if (hasEdited) {
        setSelectedSubmitType("edit");
      } else if (approveAllowed) {
        setSelectedSubmitType("approve");
      } else if (isEditAllowed) {
        setSelectedSubmitType("edit");
      }
    } else {
      setSelectedSubmitType("reject");
    }

    setHumanResponse((prev) =>
      prev.map((existing) =>
        existing.type === "reject"
          ? { type: "reject", message: change }
          : existing,
      ),
    );
  };

  const handleReset = () => {
    setHumanResponse((prev) =>
      prev.map((response) => {
        if (response.type === "edit") {
          const resetArgs = Object.fromEntries(
            Object.keys(response.edited_action.args).map((key) => [
              key,
              initialValues[key] ?? stringifyArgValue(actionArgs[key]),
            ]),
          );

          return {
            ...response,
            edited_action: {
              name: response.edited_action.name,
              args: resetArgs,
            },
            editsMade: false,
          };
        }

        if (response.type === "reject") {
          return { type: "reject", message: "" };
        }

        return response;
      }),
    );
    setHasEdited(false);
    setHasAddedResponse(false);
    setDefaultSubmitType();
  };

  const handleAutoApprovalChange = (enabled: boolean) => {
    if (!actionName) return;

    const toolLabel = prettifyText(actionName);
    setToolAutoApproved(actionName, enabled);
    setAutoApproveEnabled(enabled);
    toast(
      enabled ? `以后${toolLabel}会自动批准。` : `已恢复${toolLabel}人工确认。`,
      {
        duration: 3000,
      },
    );
  };

  const submitWithType =
    (submitType: SubmitType) =>
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
      setSelectedSubmitType(submitType);
      void handleSubmit(event, submitType);
    };

  const submitWithKeyboard = (
    event: React.KeyboardEvent,
    submitType: SubmitType,
  ) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      setSelectedSubmitType(submitType);
      void handleSubmit(event, submitType);
    }
  };

  const showRejectForm =
    isRejectAllowed &&
    (selectedSubmitType === "reject" ||
      hasAddedResponse ||
      (!approveAllowed && !isEditAllowed));
  const showAutoApproval =
    approveAllowed && !!actionName && isToolAutoApprovalSupported(actionName);
  const primarySubmitType: SubmitType | undefined = hasEdited
    ? "edit"
    : approveAllowed
      ? "approve"
      : isEditAllowed
        ? "edit"
        : undefined;
  const primaryButtonText = primarySubmitType === "edit" ? "提交修改" : "批准";

  return (
    <div className="flex w-full max-w-full min-w-0 flex-col items-start justify-start gap-2">
      <section className="border-border bg-background flex w-full min-w-0 flex-col gap-4 rounded-lg border p-3 shadow-sm sm:gap-6 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold">审核工具调用</h3>
            {actionName ? (
              <p className="text-muted-foreground mt-1 text-sm">
                {prettifyText(actionName)}
              </p>
            ) : null}
          </div>
          {(editResponse || rejectResponse) && (
            <ResetButton handleReset={handleReset} />
          )}
        </div>

        {editResponse ? (
          <div className="flex w-full flex-col gap-4">
            {Object.entries(editResponse.edited_action.args).map(
              ([key, value]) => {
                const stringValue = stringifyArgValue(value);

                return (
                  <div
                    key={`edit-${key}`}
                    className="flex w-full flex-col gap-2"
                  >
                    <label className="text-sm font-medium">
                      {prettifyText(key)}
                    </label>
                    <Textarea
                      value={stringValue}
                      onChange={(event) =>
                        onEditChange(event.target.value, editResponse, key)
                      }
                      onKeyDown={(event) =>
                        submitWithKeyboard(
                          event,
                          hasEdited
                            ? "edit"
                            : approveAllowed
                              ? "approve"
                              : "edit",
                        )
                      }
                      className="min-h-24 resize-y text-base"
                    />
                  </div>
                );
              },
            )}
          </div>
        ) : hasArgs ? (
          <div className="flex w-full flex-col gap-3">
            <p className="text-sm font-medium">请求参数</p>
            <ArgsRenderer args={actionArgs} />
          </div>
        ) : null}

        {showAutoApproval && (
          <label className="bg-muted/30 flex w-full items-start gap-3 rounded-md border px-3 py-2.5 text-sm">
            <input
              type="checkbox"
              checked={autoApproveEnabled}
              onChange={(event) =>
                handleAutoApprovalChange(event.currentTarget.checked)
              }
              className="mt-0.5 h-4 w-4 accent-[#2F6868]"
            />
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="font-medium">
                以后{prettifyText(actionName)}不再询问
              </span>
              <span className="text-muted-foreground leading-5">
                开启后，后续{prettifyText(actionName)}会在本浏览器自动批准。
              </span>
            </span>
          </label>
        )}

        {isRejectAllowed && (
          <div className="flex w-full flex-col gap-3">
            {showRejectForm ? (
              <div className="flex w-full flex-col gap-2">
                <label className="text-sm font-medium">拒绝原因</label>
                <Textarea
                  value={rejectResponse?.message ?? ""}
                  onChange={(event) =>
                    rejectResponse &&
                    onRejectChange(event.target.value, rejectResponse)
                  }
                  onFocus={() => setSelectedSubmitType("reject")}
                  onKeyDown={(event) => submitWithKeyboard(event, "reject")}
                  placeholder="请填写拒绝原因或给智能体的反馈..."
                  className="min-h-24 resize-y text-base"
                />
              </div>
            ) : null}
          </div>
        )}

        <div className="flex w-full flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-muted-foreground text-xs leading-5">
            {isLoading
              ? "正在提交处理结果..."
              : selectedSubmitType && supportsMultipleMethods
                ? `当前处理：${prettifyText(selectedSubmitType)}`
                : "确认后会继续执行工具并生成回答。"}
          </div>
          <div className="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
            {isRejectAllowed &&
              (showRejectForm ? (
                <Button
                  variant="outline"
                  className="w-full border-red-300 text-red-600 hover:bg-red-50 hover:text-red-700 sm:w-auto"
                  onClick={submitWithType("reject")}
                  disabled={isLoading}
                >
                  <X className="h-4 w-4" />
                  提交拒绝
                </Button>
              ) : (
                <Button
                  variant="outline"
                  className="w-full sm:w-auto"
                  onClick={() => setSelectedSubmitType("reject")}
                  disabled={isLoading}
                >
                  <X className="h-4 w-4" />
                  拒绝
                </Button>
              ))}
            {primarySubmitType && (
              <Button
                variant="brand"
                className="w-full sm:w-auto"
                onClick={submitWithType(primarySubmitType)}
                disabled={isLoading}
              >
                <Check className="h-4 w-4" />
                {primaryButtonText}
              </Button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
