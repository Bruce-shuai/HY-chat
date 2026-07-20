import { useStreamContext } from "@/providers/Stream";
import { END } from "@langchain/langgraph/web";
import { Interrupt } from "@langchain/langgraph-sdk";
import { toast } from "sonner";
import {
  Dispatch,
  KeyboardEvent,
  MutableRefObject,
  SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";
import { Decision, DecisionWithEdits, HITLRequest, SubmitType } from "../types";
import { buildDecisionFromState, createDefaultHumanResponse } from "../utils";
import { isAlreadyConsumedInterruptError } from "@/lib/stream-errors";

interface UseInterruptedActionsInput {
  interrupt: Interrupt<HITLRequest>;
}

interface UseInterruptedActionsValue {
  handleSubmit: (
    e: React.MouseEvent<HTMLButtonElement, MouseEvent> | KeyboardEvent,
    submitTypeOverride?: SubmitType,
  ) => Promise<void>;
  handleResolve: (
    e: React.MouseEvent<HTMLButtonElement, MouseEvent>,
  ) => Promise<void>;
  streaming: boolean;
  streamFinished: boolean;
  loading: boolean;
  supportsMultipleMethods: boolean;
  hasEdited: boolean;
  hasAddedResponse: boolean;
  approveAllowed: boolean;
  humanResponse: DecisionWithEdits[];
  selectedSubmitType: SubmitType | undefined;
  setSelectedSubmitType: Dispatch<SetStateAction<SubmitType | undefined>>;
  setHumanResponse: Dispatch<SetStateAction<DecisionWithEdits[]>>;
  setHasAddedResponse: Dispatch<SetStateAction<boolean>>;
  setHasEdited: Dispatch<SetStateAction<boolean>>;
  initialHumanInterruptEditValue: MutableRefObject<Record<string, string>>;
}

export default function useInterruptedActions({
  interrupt,
}: UseInterruptedActionsInput): UseInterruptedActionsValue {
  const thread = useStreamContext();
  const [humanResponse, setHumanResponse] = useState<DecisionWithEdits[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamFinished, setStreamFinished] = useState(false);
  const [selectedSubmitType, setSelectedSubmitType] = useState<SubmitType>();
  const [hasEdited, setHasEdited] = useState(false);
  const [hasAddedResponse, setHasAddedResponse] = useState(false);
  const [approveAllowed, setApproveAllowed] = useState(false);
  const initialHumanInterruptEditValue = useRef<Record<string, string>>({});
  const submittingRef = useRef(false);

  useEffect(() => {
    const hitlValue = interrupt.value as HITLRequest | undefined;
    initialHumanInterruptEditValue.current = {};
    submittingRef.current = false;

    if (!hitlValue) {
      setHumanResponse([]);
      setSelectedSubmitType(undefined);
      setApproveAllowed(false);
      setHasEdited(false);
      setHasAddedResponse(false);
      return;
    }

    try {
      const { responses, defaultSubmitType, hasApprove } =
        createDefaultHumanResponse(hitlValue, initialHumanInterruptEditValue);
      setHumanResponse(responses);
      setSelectedSubmitType(defaultSubmitType);
      setApproveAllowed(hasApprove);
      setHasEdited(false);
      setHasAddedResponse(false);
    } catch (error) {
      console.error("Error formatting and setting human response state", error);
      setHumanResponse([]);
      setSelectedSubmitType(undefined);
      setApproveAllowed(false);
    }
  }, [interrupt]);

  const resumeRun = async (
    decisions: Decision[],
  ): Promise<"success" | "already-consumed" | "error"> => {
    try {
      await thread.respond({ decisions });
      return "success";
    } catch (error) {
      if (isAlreadyConsumedInterruptError(error)) {
        return "already-consumed";
      }

      console.error("Error sending human response", error);
      return "error";
    }
  };

  const handleSubmit = async (
    e: React.MouseEvent<HTMLButtonElement, MouseEvent> | KeyboardEvent,
    submitTypeOverride?: SubmitType,
  ) => {
    e.preventDefault();

    if (submittingRef.current) {
      return;
    }

    const { decision, error } = buildDecisionFromState(
      humanResponse,
      submitTypeOverride ?? selectedSubmitType,
    );

    if (!decision) {
      toast.error("错误", {
        description: error ?? "暂不支持这种处理方式。",
        duration: 5000,
        richColors: true,
        closeButton: true,
      });
      return;
    }

    if (error) {
      toast.error("错误", {
        description: error,
        duration: 5000,
        richColors: true,
        closeButton: true,
      });
      return;
    }

    let errorOccurred = false;
    initialHumanInterruptEditValue.current = {};
    submittingRef.current = true;

    try {
      setLoading(true);
      setStreaming(true);

      const resumeStatus = await resumeRun([decision]);
      if (resumeStatus === "already-consumed") {
        toast("已处理", {
          description: "这个工具调用已经被处理，正在同步最新状态。",
          duration: 3000,
        });
        setStreamFinished(true);
        return;
      }

      if (resumeStatus === "error") {
        errorOccurred = true;
        return;
      }

      toast("成功", {
        description: "处理结果已提交。",
        duration: 5000,
      });

      setStreamFinished(true);
    } catch (error: any) {
      console.error("Error sending human response", error);
      errorOccurred = true;

      if ("message" in error && error.message.includes("Invalid assistant")) {
        toast("错误：助手标识无效", {
          description: "当前图中找不到这个助手标识。请在设置中更新后重试。",
          richColors: true,
          closeButton: true,
          duration: 5000,
        });
      } else {
        toast.error("错误", {
          description: "提交处理结果失败。",
          richColors: true,
          closeButton: true,
          duration: 5000,
        });
      }
    } finally {
      setStreaming(false);
      setLoading(false);
      submittingRef.current = false;
      if (errorOccurred) {
        setStreamFinished(false);
      }
    }
  };

  const handleResolve = async (
    e: React.MouseEvent<HTMLButtonElement, MouseEvent>,
  ) => {
    e.preventDefault();
    setLoading(true);
    initialHumanInterruptEditValue.current = {};

    try {
      await thread.respond(null, { goto: END });

      toast("成功", {
        description: "已标记为已解决。",
        duration: 3000,
      });
    } catch (error) {
      console.error("Error marking thread as resolved", error);
      toast.error("错误", {
        description: "标记为已解决失败。",
        richColors: true,
        closeButton: true,
        duration: 3000,
      });
    } finally {
      setLoading(false);
    }
  };

  const supportsMultipleMethods =
    humanResponse.filter((response) =>
      ["edit", "approve", "reject"].includes(response.type),
    ).length > 1;

  return {
    handleSubmit,
    handleResolve,
    humanResponse,
    selectedSubmitType,
    streaming,
    streamFinished,
    loading,
    supportsMultipleMethods,
    hasEdited,
    hasAddedResponse,
    approveAllowed,
    setSelectedSubmitType,
    setHumanResponse,
    setHasAddedResponse,
    setHasEdited,
    initialHumanInterruptEditValue,
  };
}
