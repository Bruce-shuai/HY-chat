import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Interrupt } from "@langchain/langgraph-sdk";
import { Button } from "@/components/ui/button";
import { ThreadIdCopyable } from "./thread-id";
import { InboxItemInput } from "./inbox-item-input";
import useInterruptedActions from "../hooks/use-interrupted-actions";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useQueryState } from "nuqs";
import {
  constructOpenInStudioURL,
  buildDecisionFromState,
  isToolAutoApprovalSupported,
  isToolAutoApproved,
  prettifyText,
} from "../utils";
import { Decision, HITLRequest, DecisionType, ActionRequest } from "../types";
import { useStreamContext } from "@/providers/Stream";
import {
  isAlreadyConsumedInterruptError,
  isTransientInterruptResumeError,
} from "@/lib/stream-errors";

interface ThreadActionsViewProps {
  interrupt: Interrupt<HITLRequest>;
  handleShowSidePanel: (showState: boolean, showDescription: boolean) => void;
  showState: boolean;
  showDescription: boolean;
}

type AutoApprovalFailure = {
  requestKey: string;
  toolName: string;
};

function ButtonGroup({
  handleShowState,
  handleShowDescription,
  showingState,
  showingDescription,
}: {
  handleShowState: () => void;
  handleShowDescription: () => void;
  showingState: boolean;
  showingDescription: boolean;
}) {
  return (
    <div className="flex flex-row items-center justify-center gap-0">
      <Button
        variant="outline"
        className={cn(
          "rounded-l-md rounded-r-none border-r-[0px]",
          showingState ? "text-foreground" : "bg-background",
        )}
        size="sm"
        onClick={handleShowState}
      >
        状态
      </Button>
      <Button
        variant="outline"
        className={cn(
          "rounded-l-none rounded-r-md border-l-[0px]",
          showingDescription ? "text-foreground" : "bg-background",
        )}
        size="sm"
        onClick={handleShowDescription}
      >
        说明
      </Button>
    </div>
  );
}

function isValidHitlRequest(
  interrupt: Interrupt<HITLRequest>,
): interrupt is Interrupt<HITLRequest> & { value: HITLRequest } {
  return (
    !!interrupt.value &&
    Array.isArray(interrupt.value.action_requests) &&
    interrupt.value.action_requests.length > 0 &&
    Array.isArray(interrupt.value.review_configs) &&
    interrupt.value.review_configs.length > 0
  );
}

function getDecisionStatus(
  decision: Decision | undefined,
): DecisionType | null {
  if (!decision) return null;
  return decision.type;
}

function getActionTitle(action?: ActionRequest) {
  return action?.name ? prettifyText(action.name) : "未知中断";
}

const AUTO_APPROVAL_RETRY_DELAYS_MS = [800, 1600, 3000];

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function ThreadActionsView({
  interrupt,
  handleShowSidePanel,
  showDescription,
  showState,
}: ThreadActionsViewProps) {
  const stream = useStreamContext();
  const [threadId] = useQueryState("threadId");
  const [apiUrl] = useQueryState("apiUrl");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [addressedActions, setAddressedActions] = useState<
    Map<number, Decision>
  >(new Map());
  const [submittingAll, setSubmittingAll] = useState(false);
  const [autoApproving, setAutoApproving] = useState(false);
  const [autoApprovalFailure, setAutoApprovalFailure] =
    useState<AutoApprovalFailure | null>(null);
  const autoApprovedRequestKey = useRef<string | null>(null);

  const hitlValue = interrupt.value;
  const actionRequests = useMemo(
    () => hitlValue?.action_requests ?? [],
    [hitlValue?.action_requests],
  );
  const reviewConfigs = useMemo(
    () => hitlValue?.review_configs ?? [],
    [hitlValue?.review_configs],
  );

  const hasMultipleActions = actionRequests.length > 1;
  const currentAction = actionRequests[currentIndex];
  const matchingConfig =
    reviewConfigs.find(
      (config) => config.action_name === currentAction?.name,
    ) ?? reviewConfigs[currentIndex];

  const singleActionInterrupt = useMemo(() => {
    if (!currentAction || !matchingConfig) {
      return interrupt;
    }

    return {
      ...interrupt,
      value: {
        action_requests: [currentAction],
        review_configs: [matchingConfig],
      },
    };
  }, [interrupt, currentAction, matchingConfig]);

  const {
    approveAllowed,
    hasEdited,
    hasAddedResponse,
    streaming,
    supportsMultipleMethods,
    streamFinished,
    loading,
    handleSubmit,
    handleResolve,
    setSelectedSubmitType,
    setHasAddedResponse,
    setHasEdited,
    humanResponse,
    setHumanResponse,
    selectedSubmitType,
    initialHumanInterruptEditValue,
  } = useInterruptedActions({
    interrupt: singleActionInterrupt,
  });

  useEffect(() => {
    setCurrentIndex(0);
    setAddressedActions(new Map());
    setAutoApprovalFailure(null);
    autoApprovedRequestKey.current = null;
  }, [interrupt]);

  const autoApproveRequestKey = useMemo(() => {
    if (!currentAction?.name) return undefined;

    return `${currentAction.name}:${JSON.stringify(currentAction.args ?? {})}`;
  }, [currentAction?.args, currentAction?.name]);
  const autoApprovalFailedForCurrent =
    !!autoApproveRequestKey &&
    autoApprovalFailure?.requestKey === autoApproveRequestKey;

  useEffect(() => {
    if (
      hasMultipleActions ||
      !currentAction?.name ||
      !approveAllowed ||
      loading ||
      streaming ||
      submittingAll ||
      streamFinished ||
      !autoApproveRequestKey ||
      autoApprovalFailedForCurrent ||
      !isToolAutoApprovalSupported(currentAction.name) ||
      !isToolAutoApproved(currentAction.name)
    ) {
      return;
    }

    if (autoApprovedRequestKey.current === autoApproveRequestKey) {
      return;
    }

    autoApprovedRequestKey.current = autoApproveRequestKey;
    let isMounted = true;

    const approveCurrentTool = async () => {
      try {
        setAutoApproving(true);
        setAutoApprovalFailure(null);
        for (
          let attempt = 0;
          attempt <= AUTO_APPROVAL_RETRY_DELAYS_MS.length;
          attempt += 1
        ) {
          try {
            await stream.respond({ decisions: [{ type: "approve" }] });
            break;
          } catch (error) {
            if (isAlreadyConsumedInterruptError(error)) {
              if (isMounted) {
                toast("已处理", {
                  description: "这个工具调用已经被处理，正在同步最新状态。",
                  duration: 3000,
                });
              }
              return;
            }

            const canRetry =
              attempt < AUTO_APPROVAL_RETRY_DELAYS_MS.length &&
              isTransientInterruptResumeError(error);
            if (!canRetry) {
              throw error;
            }

            await wait(AUTO_APPROVAL_RETRY_DELAYS_MS[attempt]);
            if (!isMounted) return;
          }
        }

        if (isMounted) {
          toast("成功", {
            description: `已按偏好自动批准${prettifyText(currentAction.name)}。`,
            duration: 3000,
          });
        }
      } catch (error) {
        console.error("Error auto approving tool call", error);
        autoApprovedRequestKey.current = null;

        if (isMounted) {
          setAutoApprovalFailure({
            requestKey: autoApproveRequestKey,
            toolName: currentAction.name,
          });
          toast.error("错误", {
            description: `自动批准${prettifyText(currentAction.name)}没有完成，已切换为手动处理。`,
            richColors: true,
            closeButton: true,
            duration: 5000,
          });
        }
      } finally {
        if (isMounted) {
          setAutoApproving(false);
        }
      }
    };

    void approveCurrentTool();

    return () => {
      isMounted = false;
    };
  }, [
    approveAllowed,
    autoApprovalFailedForCurrent,
    autoApproveRequestKey,
    currentAction?.name,
    hasMultipleActions,
    loading,
    stream,
    streamFinished,
    streaming,
    submittingAll,
  ]);

  const handleOpenInStudio = () => {
    if (!apiUrl) {
      toast.error("错误", {
        description: "请先在设置中填写调试服务地址。",
        duration: 5000,
        richColors: true,
        closeButton: true,
      });
      return;
    }

    const studioUrl = constructOpenInStudioURL(apiUrl, threadId ?? undefined);
    window.open(studioUrl, "_blank");
  };

  const handleApproveAll = useCallback(async () => {
    if (!hasMultipleActions) return;

    try {
      const allDecisions: Decision[] = actionRequests.map(() => ({
        type: "approve",
      }));

      await stream.respond({ decisions: allDecisions });

      toast("成功", {
        description: "已批准全部操作。",
        duration: 5000,
      });
    } catch (error) {
      console.error("Error approving all actions", error);
      toast.error("错误", {
        description: "全部批准失败。",
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
    }
  }, [actionRequests, hasMultipleActions, stream]);

  const handleSubmitAll = useCallback(async () => {
    if (!hasMultipleActions) return;

    if (addressedActions.size !== actionRequests.length) {
      toast.error("错误", {
        description: `请先处理全部 ${actionRequests.length} 个操作再提交。`,
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
      return;
    }

    try {
      setSubmittingAll(true);
      const allDecisions = actionRequests.map((_, index) => {
        const decision = addressedActions.get(index);
        if (!decision) {
          throw new Error(`第 ${index + 1} 个操作缺少处理结果`);
        }
        return decision;
      });

      await stream.respond({ decisions: allDecisions });

      toast("成功", {
        description: "全部处理结果已提交。",
        duration: 5000,
      });
      setAddressedActions(new Map());
    } catch (error) {
      console.error("Error submitting all actions", error);
      toast.error("错误", {
        description: "提交处理结果失败。",
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
    } finally {
      setSubmittingAll(false);
    }
  }, [actionRequests, addressedActions, hasMultipleActions, stream]);

  const allAllowApprove = useMemo(() => {
    if (!hasMultipleActions) return false;
    return actionRequests.every((actionRequest) => {
      const matching = reviewConfigs.find(
        (config) => config.action_name === actionRequest.name,
      );
      return matching?.allowed_decisions.includes("approve");
    });
  }, [actionRequests, reviewConfigs, hasMultipleActions]);

  const handleSaveDecision = (
    e?: React.MouseEvent<HTMLButtonElement, MouseEvent> | React.KeyboardEvent,
    submitTypeOverride?: DecisionType,
  ) => {
    e?.preventDefault();
    const { decision, error } = buildDecisionFromState(
      humanResponse,
      submitTypeOverride ?? selectedSubmitType,
    );

    if (!decision || error) {
      toast.error("错误", {
        description: error ?? "无法确定当前处理方式。",
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
      return;
    }

    setAddressedActions((prev) => {
      const next = new Map(prev);
      next.set(currentIndex, decision);
      return next;
    });

    toast("成功", {
      description: `已记录第 ${currentIndex + 1} 个操作。`,
      duration: 3000,
    });

    if (currentIndex < actionRequests.length - 1) {
      setCurrentIndex((prev) => Math.min(actionRequests.length - 1, prev + 1));
    }
  };

  const currentTitle = getActionTitle(currentAction);
  const hasAllDecisions =
    hasMultipleActions && addressedActions.size === actionRequests.length;
  const autoApprovalSupported =
    approveAllowed &&
    !!currentAction?.name &&
    isToolAutoApprovalSupported(currentAction.name);
  const autoApprovalEnabledForCurrent =
    autoApprovalSupported &&
    isToolAutoApproved(currentAction?.name) &&
    !autoApprovalFailedForCurrent;
  const currentToolLabel = currentAction?.name
    ? prettifyText(currentAction.name)
    : "当前工具";
  const actionsDisabled =
    loading ||
    streaming ||
    submittingAll ||
    autoApproving ||
    autoApprovalEnabledForCurrent;

  if (!isValidHitlRequest(interrupt)) {
    return (
      <div className="bg-muted/20 flex min-h-full w-full flex-col items-center justify-center rounded-2xl p-8">
        <p className="text-muted-foreground text-sm">
          无法渲染人工确认请求，数据格式不符合预期。
        </p>
      </div>
    );
  }
  const interruptValue = singleActionInterrupt.value as HITLRequest;

  return (
    <div className="flex min-h-full w-full max-w-full flex-col gap-9">
      <div className="flex w-full flex-wrap items-center justify-between gap-3">
        <div className="flex items-center justify-start gap-3">
          <p className="text-2xl tracking-tighter text-pretty">
            {hasMultipleActions
              ? `${currentTitle} (${currentIndex + 1}/${actionRequests.length})`
              : currentTitle}
          </p>
          {threadId && <ThreadIdCopyable threadId={threadId} />}
        </div>
        <div className="flex flex-row items-center justify-start gap-2">
          {apiUrl && (
            <Button
              size="sm"
              variant="outline"
              className="bg-background flex items-center gap-1"
              onClick={handleOpenInStudio}
            >
              在调试台打开
            </Button>
          )}
          <ButtonGroup
            handleShowState={() => handleShowSidePanel(true, false)}
            handleShowDescription={() => handleShowSidePanel(false, true)}
            showingState={showState}
            showingDescription={showDescription}
          />
        </div>
      </div>

      <p className="text-muted-foreground bg-muted/30 rounded-lg border px-3 py-2 text-sm">
        此工具调用需要人工确认。点击“批准”后才会真正执行工具，并继续生成回答；也可以修改参数后提交，或填写原因拒绝。
        {autoApprovalSupported
          ? ` ${currentToolLabel}支持勾选“以后不再询问”，后续会在本浏览器自动批准。`
          : ""}
      </p>

      {autoApprovalFailedForCurrent && autoApprovalFailure && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p className="font-medium">
            自动批准{prettifyText(autoApprovalFailure.toolName)}
            没有完成，图片还没有生成。
          </p>
          <p className="mt-1 text-amber-800">
            你可以在下方点击“批准”继续执行工具；如果不想继续，也可以填写原因拒绝。
          </p>
        </div>
      )}

      <div className="flex w-full flex-row flex-wrap items-center justify-start gap-2">
        <Button
          variant="outline"
          className="bg-background text-foreground border-gray-500 font-normal"
          onClick={handleResolve}
          disabled={actionsDisabled}
        >
          标记为已解决
        </Button>
        {hasMultipleActions && allAllowApprove && (
          <Button
            variant="outline"
            className="bg-background text-foreground border-gray-500 font-normal"
            onClick={handleApproveAll}
            disabled={actionsDisabled}
          >
            全部批准
          </Button>
        )}
      </div>

      {hasMultipleActions && (
        <div className="flex w-full items-center gap-2">
          {actionRequests.map((_, index) => {
            const status = getDecisionStatus(addressedActions.get(index));
            return (
              <button
                type="button"
                key={index}
                onClick={() => setCurrentIndex(index)}
                className={cn(
                  "h-2 flex-1 rounded-full border transition-colors",
                  "border-border bg-muted",
                  status === "approve" && "border-emerald-500 bg-emerald-200",
                  status === "reject" && "border-red-500 bg-red-200",
                  status === "edit" && "border-amber-500 bg-amber-200",
                  index === currentIndex &&
                    "outline-primary outline-2 outline-offset-2",
                )}
              >
                <span className="sr-only">操作 {index + 1}</span>
              </button>
            );
          })}
        </div>
      )}

      <InboxItemInput
        approveAllowed={approveAllowed}
        hasEdited={hasEdited}
        hasAddedResponse={hasAddedResponse}
        interruptValue={interruptValue}
        humanResponse={humanResponse}
        initialValues={initialHumanInterruptEditValue.current}
        setHumanResponse={setHumanResponse}
        supportsMultipleMethods={supportsMultipleMethods}
        setSelectedSubmitType={setSelectedSubmitType}
        setHasAddedResponse={setHasAddedResponse}
        setHasEdited={setHasEdited}
        handleSubmit={hasMultipleActions ? handleSaveDecision : handleSubmit}
        isLoading={
          hasMultipleActions
            ? submittingAll
            : loading || autoApproving || autoApprovalEnabledForCurrent
        }
        selectedSubmitType={selectedSubmitType}
      />

      {autoApproving && (
        <p className="text-muted-foreground text-sm">
          已按偏好自动批准{currentToolLabel}，正在继续生成回答…
        </p>
      )}

      {hasMultipleActions && (
        <div className="flex w-full items-center justify-between">
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={currentIndex === 0}
              onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
            >
              上一个
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={currentIndex === actionRequests.length - 1}
              onClick={() =>
                setCurrentIndex((prev) =>
                  Math.min(actionRequests.length - 1, prev + 1),
                )
              }
            >
              下一个
            </Button>
          </div>
          <Button
            variant="brand"
            disabled={!hasAllDecisions || submittingAll}
            onClick={handleSubmitAll}
          >
            {submittingAll
              ? "正在提交..."
              : `提交全部 ${actionRequests.length} 个处理结果`}
          </Button>
        </div>
      )}

      {!hasMultipleActions && streamFinished && (
        <p className="text-base font-medium text-green-600">图执行已完成。</p>
      )}
    </div>
  );
}
