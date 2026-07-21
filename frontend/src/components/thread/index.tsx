import { v4 as uuidv4 } from "uuid";
import type { CSSProperties, FormEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";
import { Button } from "../ui/button";
import { HumanMessage as HumanMessageClass } from "@langchain/core/messages";
import { ensureToolCallsHaveResponses } from "@/lib/ensure-tool-responses";
import { BrandLogo } from "../brand-logo";
import { TooltipIconButton } from "./tooltip-icon-button";
import {
  ArrowDown,
  LoaderCircle,
  PanelRightOpen,
  PanelRightClose,
  SquarePen,
  XIcon,
  Plus,
  BookOpen,
} from "lucide-react";
import { useQueryState, parseAsBoolean } from "nuqs";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import { ThreadHistory } from "@/features/threads";
import { toast } from "sonner";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { useFileUpload } from "@/hooks/use-file-upload";
import { UPLOAD_ATTACHMENT_ACCEPT } from "@/lib/multimodal-utils";
import { ContentBlocksPreview } from "./ContentBlocksPreview";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { useAuth } from "@/providers/Auth";
import {
  getKnownStreamErrorInfo,
  isAlreadyConsumedInterruptError,
} from "@/lib/stream-errors";
import {
  useArtifactOpen,
  ArtifactContent,
  ArtifactTitle,
  useArtifactContext,
} from "./artifact";
import { ThreadMessageList } from "./message-list";
import { useThreadMessageState } from "./hooks/use-thread-message-state";

function StickyToBottomContent(props: {
  content: ReactNode;
  footer?: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const context = useStickToBottomContext();
  return (
    <>
      <div
        ref={context.scrollRef}
        style={{ width: "100%", height: "100%" }}
        className={props.className}
      >
        <div
          ref={context.contentRef}
          className={props.contentClassName}
        >
          {props.content}
        </div>
      </div>

      {props.footer}
    </>
  );
}

function ScrollToBottom(props: { className?: string }) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  if (isAtBottom) return null;
  return (
    <Button
      variant="outline"
      className={props.className}
      onClick={() => scrollToBottom()}
    >
      <ArrowDown className="h-4 w-4" />
      <span>滚动到底部</span>
    </Button>
  );
}

export function Thread() {
  const { authFetch } = useAuth();
  const [artifactContext, setArtifactContext] = useArtifactContext();
  const [artifactOpen, closeArtifact] = useArtifactOpen();

  const [threadId, _setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );
  const [hideToolCalls, setHideToolCalls] = useQueryState(
    "hideToolCalls",
    parseAsBoolean.withDefault(true),
  );
  const showToolCalls = !(hideToolCalls ?? true);
  const [input, setInput] = useState("");
  const [models, setModels] = useState<
    Array<{ id: string; label: string; is_default: boolean }>
  >([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [knowledgeUploading, setKnowledgeUploading] = useState(false);
  const knowledgeInputRef = useRef<HTMLInputElement>(null);
  const footerRef = useRef<HTMLDivElement>(null);
  const [footerHeight, setFooterHeight] = useState(176);
  const {
    contentBlocks,
    setContentBlocks,
    handleFileUpload,
    dropRef,
    removeBlock,
    resetBlocks: _resetBlocks,
    dragOver,
    handlePaste,
  } = useFileUpload();
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");

  const stream = useStreamContext();
  const messages = stream.messages;
  const isLoading = stream.isLoading;
  const {
    chatStarted,
    firstTokenReceived,
    hasNoAIOrToolMessages,
    isThreadLoading,
    messageListResetKey,
    visibleMessages,
    waitForFirstToken,
  } = useThreadMessageState({
    threadId,
    streamThreadId: stream.threadId ?? null,
    isStreamThreadLoading: stream.isThreadLoading,
    messages,
    hasInterrupt: !!stream.interrupt,
  });

  const lastError = useRef<string | undefined>(undefined);

  useEffect(() => {
    const footer = footerRef.current;
    if (!footer) return;

    const updateFooterHeight = () => {
      const nextHeight = Math.ceil(footer.getBoundingClientRect().height);
      setFooterHeight((currentHeight) =>
        Math.abs(currentHeight - nextHeight) > 1 ? nextHeight : currentHeight,
      );
    };

    updateFooterHeight();
    const observer = new ResizeObserver(updateFooterHeight);
    observer.observe(footer);
    window.addEventListener("resize", updateFooterHeight);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateFooterHeight);
    };
  }, [chatStarted]);

  useEffect(() => {
    const backendUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    authFetch(`${backendUrl}/models`)
      .then((response) => {
        if (!response.ok) throw new Error("模型列表加载失败");
        return response.json();
      })
      .then((payload) => {
        setModels(payload.models ?? []);
        const stored = window.localStorage.getItem("hy-chat:model");
        const available = (payload.models ?? []).some(
          (model: { id: string }) => model.id === stored,
        );
        setSelectedModel(
          available
            ? stored || ""
            : payload.current_model || payload.models?.[0]?.id || "",
        );
      })
      .catch((error) => console.warn(error));
  }, [authFetch]);

  const changeModel = (model: string) => {
    setSelectedModel(model);
    window.localStorage.setItem("hy-chat:model", model);
  };

  const uploadKnowledgeDocument = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    setKnowledgeUploading(true);
    const backendUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    try {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        const response = await authFetch(`${backendUrl}/rag/documents`, {
          method: "POST",
          body: form,
        });
        const result = await response.json();
        if (!response.ok) {
          throw new Error(result.detail || `${file.name} 上传失败`);
        }
        toast.success(`${file.name} 已加入知识库`, {
          description: `${result.chunk_count} 个检索片段`,
        });
      }
    } catch (error) {
      toast.error("知识库上传失败", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setKnowledgeUploading(false);
      event.target.value = "";
    }
  };

  const setThreadId = (id: string | null) => {
    _setThreadId(id);

    // close artifact and reset artifact context
    closeArtifact();
    setArtifactContext({});
  };

  useEffect(() => {
    if (!stream.error) {
      lastError.current = undefined;
      return;
    }
    try {
      const message = (stream.error as any).message;
      if (!message || lastError.current === message) {
        // Message has already been logged. do not modify ref, return early.
        return;
      }

      if (isAlreadyConsumedInterruptError(message)) {
        lastError.current = message;
        return;
      }

      console.error("会话运行异常", stream.error);

      // Message is defined, and it has not been logged yet. Save it, and send the error
      lastError.current = message;
      const knownError = getKnownStreamErrorInfo(stream.error);
      toast.error(knownError?.title ?? "出错了，请稍后重试。", {
        description:
          knownError?.description ?? "请求处理失败，请刷新页面或稍后再试。",
        richColors: true,
        closeButton: true,
      });
    } catch {
      // no-op
    }
  }, [stream.error]);

  const runError =
    stream.error && !isAlreadyConsumedInterruptError(stream.error)
      ? stream.error
      : undefined;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (
      (input.trim().length === 0 && contentBlocks.length === 0) ||
      isLoading ||
      isThreadLoading
    )
      return;
    waitForFirstToken();

    const newHumanMessage = new HumanMessageClass({
      id: uuidv4(),
      content: [
        ...(input.trim().length > 0 ? [{ type: "text", text: input }] : []),
        ...contentBlocks,
      ],
    });

    const toolMessages = ensureToolCallsHaveResponses(stream.messages);

    const context =
      Object.keys(artifactContext).length > 0 ? artifactContext : undefined;

    stream.submit({
      messages: [...toolMessages, newHumanMessage],
      context,
      selected_model: selectedModel || undefined,
    });

    setInput("");
    setContentBlocks([]);
  };

  const handleRegenerate = (parentCheckpointId: string | undefined) => {
    waitForFirstToken();
    stream.submit(undefined, {
      forkFrom: parentCheckpointId,
    });
  };

  return (
    <div className="bg-background flex h-dvh w-full overflow-hidden">
      <div className="relative hidden lg:flex">
        <motion.div
          className="bg-background absolute z-20 h-full overflow-hidden border-r"
          style={{ width: 300 }}
          animate={
            isLargeScreen
              ? { x: chatHistoryOpen ? 0 : -300 }
              : { x: chatHistoryOpen ? 0 : -300 }
          }
          initial={{ x: -300 }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 30 }
              : { duration: 0 }
          }
        >
          <div
            className="relative h-full"
            style={{ width: 300 }}
          >
            <ThreadHistory />
          </div>
        </motion.div>
      </div>

      <div
        className={cn(
          "grid min-h-0 w-full grid-cols-[1fr_0fr] transition-all duration-500",
          artifactOpen && "lg:grid-cols-[3fr_2fr]",
        )}
      >
        <motion.div
          className={cn(
            "relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
            !chatStarted && "grid-rows-[1fr]",
          )}
          layout={isLargeScreen}
          animate={{
            marginLeft: chatHistoryOpen ? (isLargeScreen ? 300 : 0) : 0,
            width: chatHistoryOpen
              ? isLargeScreen
                ? "calc(100% - 300px)"
                : "100%"
              : "100%",
          }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 30 }
              : { duration: 0 }
          }
        >
          {!chatStarted && (
            <div className="absolute top-0 left-0 z-10 flex w-full items-center justify-between gap-3 px-3 pt-[calc(env(safe-area-inset-top)+0.5rem)] pb-2 sm:p-2 sm:pl-4">
              <div>
                {(!chatHistoryOpen || !isLargeScreen) && (
                  <Button
                    className="hover:bg-muted"
                    variant="ghost"
                    onClick={() => setChatHistoryOpen((p) => !p)}
                  >
                    {chatHistoryOpen ? (
                      <PanelRightOpen className="size-5" />
                    ) : (
                      <PanelRightClose className="size-5" />
                    )}
                  </Button>
                )}
              </div>
              <div className="absolute top-2 right-3 flex items-center">
                <AccountMenu />
              </div>
            </div>
          )}
          {chatStarted && (
            <div className="relative z-10 flex min-w-0 items-center justify-between gap-2 px-2 pt-[calc(env(safe-area-inset-top)+0.5rem)] pb-2 sm:gap-3 sm:p-2">
              <div className="relative flex min-w-0 items-center justify-start gap-2">
                <div className="absolute left-0 z-10">
                  {(!chatHistoryOpen || !isLargeScreen) && (
                    <Button
                      className="hover:bg-muted"
                      variant="ghost"
                      onClick={() => setChatHistoryOpen((p) => !p)}
                    >
                      {chatHistoryOpen ? (
                        <PanelRightOpen className="size-5" />
                      ) : (
                        <PanelRightClose className="size-5" />
                      )}
                    </Button>
                  )}
                </div>
                <motion.button
                  className="flex min-w-0 cursor-pointer items-center gap-2"
                  onClick={() => setThreadId(null)}
                  animate={{
                    marginLeft: !chatHistoryOpen ? 48 : 0,
                  }}
                  transition={{
                    type: "spring",
                    stiffness: 300,
                    damping: 30,
                  }}
                >
                  <BrandLogo className="size-9 border" />
                  <span className="truncate text-lg font-semibold tracking-tight sm:text-xl">
                    HY-chat
                  </span>
                </motion.button>
              </div>

              <div className="flex shrink-0 items-center gap-1 sm:gap-2">
                <TooltipIconButton
                  size="lg"
                  className="p-4"
                  tooltip="新建会话"
                  variant="ghost"
                  onClick={() => setThreadId(null)}
                >
                  <SquarePen className="size-5" />
                </TooltipIconButton>
                <AccountMenu />
              </div>

              <div className="from-background to-background/0 absolute inset-x-0 top-full h-5 bg-gradient-to-b" />
            </div>
          )}

          <StickToBottom
            className="relative min-h-0 flex-1 overflow-hidden"
            style={
              {
                "--thread-footer-height": `${footerHeight}px`,
              } as CSSProperties
            }
          >
            <StickyToBottomContent
              className={cn(
                "[&::-webkit-scrollbar-thumb]:bg-border absolute inset-0 overflow-y-scroll overscroll-contain px-3 sm:px-4 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-track]:bg-transparent",
              )}
              contentClassName={cn(
                "mx-auto flex min-h-full w-full max-w-3xl flex-col gap-4 pt-8 pb-[calc(var(--thread-footer-height,11rem)+1rem+env(safe-area-inset-bottom))]",
                !chatStarted && "pt-[25vh]",
              )}
              content={
                <ThreadMessageList
                  firstTokenReceived={firstTokenReceived}
                  hasInterrupt={!!stream.interrupt}
                  hasNoAIOrToolMessages={hasNoAIOrToolMessages}
                  isThreadLoading={isThreadLoading}
                  isRunLoading={isLoading}
                  runError={runError}
                  messages={visibleMessages}
                  resetKey={messageListResetKey}
                  threadId={threadId}
                  onNewThread={() => setThreadId(null)}
                  onOpenHistory={(reset) => {
                    setChatHistoryOpen(true);
                    setThreadId(null);
                    reset();
                  }}
                  onRegenerate={handleRegenerate}
                />
              }
              footer={
                <div
                  ref={footerRef}
                  className="from-background via-background to-background/0 pointer-events-none absolute inset-x-0 bottom-0 z-20 flex flex-col items-center gap-3 bg-gradient-to-t px-2 pt-12 pb-[env(safe-area-inset-bottom)] sm:gap-6 sm:px-4 sm:pt-14"
                >
                  {!chatStarted && (
                    <div className="flex items-center justify-center">
                      <BrandLogo
                        variant="wordmark"
                        className="h-28 w-32 border shadow-sm"
                        priority
                      />
                    </div>
                  )}

                  <ScrollToBottom className="animate-in fade-in-0 zoom-in-95 pointer-events-auto absolute top-2 left-1/2 -translate-x-1/2 sm:top-3" />

                  <div
                    ref={dropRef}
                    className={cn(
                      "bg-muted pointer-events-auto relative z-10 mx-auto mb-2 w-full max-w-3xl rounded-xl shadow-xs transition-all sm:mb-8 sm:rounded-2xl",
                      chatStarted &&
                        "max-h-[58dvh] overflow-hidden sm:max-h-[52dvh]",
                      dragOver
                        ? "border-primary border-2 border-dotted"
                        : "border border-solid",
                    )}
                  >
                    <form
                      onSubmit={handleSubmit}
                      className="mx-auto flex max-h-[58dvh] max-w-3xl flex-col gap-2 sm:max-h-[52dvh]"
                    >
                      <ContentBlocksPreview
                        blocks={contentBlocks}
                        onRemove={removeBlock}
                        className="max-h-28 overflow-y-auto overscroll-contain"
                      />
                      <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        disabled={isThreadLoading}
                        onPaste={handlePaste}
                        onKeyDown={(e) => {
                          if (
                            e.key === "Enter" &&
                            !e.shiftKey &&
                            !e.metaKey &&
                            !e.nativeEvent.isComposing
                          ) {
                            e.preventDefault();
                            const el = e.target as HTMLElement | undefined;
                            const form = el?.closest("form");
                            form?.requestSubmit();
                          }
                        }}
                        placeholder="给 HY-chat 发送消息…"
                        className="field-sizing-content max-h-[34dvh] min-h-12 resize-none overflow-y-auto overscroll-contain border-none bg-transparent p-3 pb-0 shadow-none ring-0 outline-none focus:ring-0 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 sm:max-h-72 sm:p-3.5 sm:pb-0"
                      />

                      <div className="flex shrink-0 flex-wrap items-center gap-1.5 p-2 pt-3 sm:gap-4">
                        <label className="text-muted-foreground flex min-w-0 items-center gap-2 text-sm">
                          <span className="hidden sm:inline">模型</span>
                          <select
                            aria-label="选择模型"
                            value={selectedModel}
                            onChange={(event) =>
                              changeModel(event.target.value)
                            }
                            className="bg-background text-foreground max-w-32 rounded-md border px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-gray-300 sm:max-w-none"
                          >
                            {!models.length && (
                              <option value="">默认模型</option>
                            )}
                            {models.map((model) => (
                              <option
                                key={model.id}
                                value={model.id}
                              >
                                {model.label}
                                {model.is_default ? "（默认）" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div>
                          <div className="flex items-center space-x-2">
                            <Switch
                              id="render-tool-calls"
                              aria-label="查看工具执行过程"
                              checked={showToolCalls}
                              onCheckedChange={(checked) =>
                                setHideToolCalls(!checked)
                              }
                            />
                            <Label
                              htmlFor="render-tool-calls"
                              className="text-muted-foreground text-sm"
                            >
                              <span className="hidden sm:inline">
                                查看工具执行过程
                              </span>
                            </Label>
                          </div>
                        </div>
                        <Label
                          htmlFor="file-input"
                          className="flex cursor-pointer items-center gap-2"
                        >
                          <Plus className="text-muted-foreground size-5" />
                          <span className="text-muted-foreground hidden text-sm md:inline">
                            上传附件
                          </span>
                        </Label>
                        <input
                          id="file-input"
                          type="file"
                          onChange={handleFileUpload}
                          multiple
                          accept={UPLOAD_ATTACHMENT_ACCEPT}
                          className="hidden"
                        />
                        <button
                          type="button"
                          onClick={() => knowledgeInputRef.current?.click()}
                          disabled={knowledgeUploading}
                          className="text-muted-foreground flex items-center gap-2 text-sm disabled:opacity-50"
                        >
                          {knowledgeUploading ? (
                            <LoaderCircle className="size-5 animate-spin" />
                          ) : (
                            <BookOpen className="size-5" />
                          )}
                          <span className="hidden md:inline">加入知识库</span>
                        </button>
                        <input
                          ref={knowledgeInputRef}
                          type="file"
                          onChange={uploadKnowledgeDocument}
                          multiple
                          accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.html,.htm,.csv,.json"
                          className="hidden"
                        />
                        {stream.isLoading ? (
                          <Button
                            key="stop"
                            onClick={() => stream.stop()}
                            className="ml-auto h-9 px-3 sm:h-10 sm:px-4"
                          >
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                            停止
                          </Button>
                        ) : (
                          <Button
                            type="submit"
                            className="ml-auto h-9 px-3 shadow-md transition-all sm:h-10 sm:px-4"
                            disabled={
                              isLoading ||
                              isThreadLoading ||
                              (!input.trim() && contentBlocks.length === 0)
                            }
                          >
                            发送
                          </Button>
                        )}
                      </div>
                    </form>
                  </div>
                </div>
              }
            />
          </StickToBottom>
        </motion.div>
        <div
          className={cn(
            "relative flex-col border-l",
            artifactOpen
              ? "bg-background fixed inset-0 z-40 flex lg:relative lg:z-auto"
              : "hidden lg:flex",
          )}
        >
          <div className="absolute inset-0 flex min-w-0 flex-col lg:min-w-[30vw]">
            <div className="grid grid-cols-[1fr_auto] border-b px-4 pt-[calc(env(safe-area-inset-top)+1rem)] pb-4 lg:p-4">
              <ArtifactTitle className="truncate overflow-hidden" />
              <button
                onClick={closeArtifact}
                className="cursor-pointer"
              >
                <XIcon className="size-5" />
              </button>
            </div>
            <ArtifactContent className="relative flex-grow" />
          </div>
        </div>
      </div>
    </div>
  );
}
