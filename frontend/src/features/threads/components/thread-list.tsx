import { useState } from "react";
import type { Thread } from "@langchain/langgraph-sdk";
import { useQueryState } from "nuqs";
import { Check, LoaderCircle, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TooltipIconButton } from "@/components/thread/tooltip-icon-button";
import { useThreads } from "@/providers/Thread";

import { getThreadTitle } from "../lib/thread-title";

type ThreadListProps = {
  threads: Thread[];
  onThreadClick?: (threadId: string) => void;
};

type ThreadTitleEditorProps = {
  draftTitle: string;
  isSaving: boolean;
  onCancel: () => void;
  onChange: (title: string) => void;
  onSubmit: () => void;
};

function ThreadTitleEditor({
  draftTitle,
  isSaving,
  onCancel,
  onChange,
  onSubmit,
}: ThreadTitleEditorProps) {
  return (
    <form
      className="flex h-10 w-full items-center gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Input
        value={draftTitle}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
        autoFocus
        disabled={isSaving}
        className="bg-background h-8 flex-1 px-2 text-sm"
        aria-label="会话名称"
      />
      <TooltipIconButton
        type="submit"
        tooltip="保存"
        disabled={isSaving}
        className="size-8"
      >
        {isSaving ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <Check className="size-4" />
        )}
      </TooltipIconButton>
      <TooltipIconButton
        type="button"
        tooltip="取消"
        disabled={isSaving}
        className="size-8"
        onClick={onCancel}
      >
        <X className="size-4" />
      </TooltipIconButton>
    </form>
  );
}

type ThreadListItemProps = {
  isActive: boolean;
  isDeleting: boolean;
  onDelete: () => void;
  onEdit: () => void;
  onOpen: () => void;
  title: string;
};

function ThreadListItem({
  isActive,
  isDeleting,
  onDelete,
  onEdit,
  onOpen,
  title,
}: ThreadListItemProps) {
  return (
    <div
      className={`hover:bg-muted/70 flex h-11 w-full items-center gap-1 rounded-md border border-transparent pr-1 transition-colors ${isActive ? "bg-muted border-border" : ""}`}
    >
      <Button
        variant="ghost"
        className={`h-10 min-w-0 flex-1 justify-start px-3 text-left font-normal hover:bg-transparent ${isActive ? "font-medium" : ""}`}
        onClick={(event) => {
          event.preventDefault();
          onOpen();
        }}
      >
        <p
          className="truncate text-ellipsis"
          title={title}
        >
          {title}
        </p>
      </Button>
      <div className="flex shrink-0 items-center gap-0.5">
        <TooltipIconButton
          type="button"
          tooltip="重命名"
          className="text-muted-foreground hover:text-foreground hover:bg-background size-8"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onEdit();
          }}
          disabled={isDeleting}
        >
          <Pencil className="size-4" />
        </TooltipIconButton>
        <TooltipIconButton
          type="button"
          tooltip="删除"
          className="text-muted-foreground hover:text-destructive hover:bg-background size-8"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onDelete();
          }}
          disabled={isDeleting}
        >
          {isDeleting ? (
            <LoaderCircle className="size-4 animate-spin" />
          ) : (
            <Trash2 className="size-4" />
          )}
        </TooltipIconButton>
      </div>
    </div>
  );
}

export function ThreadList({ threads, onThreadClick }: ThreadListProps) {
  const [threadId, setThreadId] = useQueryState("threadId");
  const { renameThread, deleteThread } = useThreads();
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [savingThreadId, setSavingThreadId] = useState<string | null>(null);
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);

  const startEditing = (thread: Thread) => {
    setEditingThreadId(thread.thread_id);
    setDraftTitle(getThreadTitle(thread));
  };

  const saveTitle = async (thread: Thread) => {
    const nextTitle = draftTitle.trim();
    if (!nextTitle) {
      toast.error("会话名称不能为空");
      return;
    }

    setSavingThreadId(thread.thread_id);
    try {
      await renameThread(thread, nextTitle);
      setEditingThreadId(null);
      toast.success("会话名称已更新");
    } catch (error) {
      console.error("重命名失败", error);
      toast.error("重命名失败", {
        description: "请稍后重试。",
      });
    } finally {
      setSavingThreadId(null);
    }
  };

  const removeThread = async (targetThreadId: string) => {
    const confirmed = window.confirm("确定删除这个会话吗？此操作无法撤销。");
    if (!confirmed) return;

    setDeletingThreadId(targetThreadId);
    try {
      await deleteThread(targetThreadId);
      if (targetThreadId === threadId) {
        await setThreadId(null);
      }
      toast.success("会话已删除");
    } catch (error) {
      console.error("删除会话失败", error);
      toast.error("删除失败", {
        description: "请稍后重试。",
      });
    } finally {
      setDeletingThreadId(null);
    }
  };

  return (
    <div className="[&::-webkit-scrollbar-thumb]:bg-border flex h-full w-full flex-col items-start justify-start gap-2 overflow-y-scroll [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-track]:bg-transparent">
      {threads.map((thread) => {
        const isActive = thread.thread_id === threadId;
        const isEditing = editingThreadId === thread.thread_id;
        const isSaving = savingThreadId === thread.thread_id;
        const isDeleting = deletingThreadId === thread.thread_id;

        return (
          <div
            key={thread.thread_id}
            className="group w-full px-1"
          >
            {isEditing ? (
              <ThreadTitleEditor
                draftTitle={draftTitle}
                isSaving={isSaving}
                onCancel={() => setEditingThreadId(null)}
                onChange={setDraftTitle}
                onSubmit={() => void saveTitle(thread)}
              />
            ) : (
              <ThreadListItem
                isActive={isActive}
                isDeleting={isDeleting}
                title={getThreadTitle(thread)}
                onDelete={() => void removeThread(thread.thread_id)}
                onEdit={() => startEditing(thread)}
                onOpen={() => {
                  onThreadClick?.(thread.thread_id);
                  if (!isActive) {
                    void setThreadId(thread.thread_id);
                  }
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
