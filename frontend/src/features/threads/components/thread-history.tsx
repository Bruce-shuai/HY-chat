import { useEffect } from "react";
import { useQueryState, parseAsBoolean } from "nuqs";
import {
  MessageSquarePlus,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useThreads } from "@/providers/Thread";

import { ThreadList } from "./thread-list";

export function ThreadHistory() {
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");
  const [, setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );

  const { getThreads, threads, setThreads, setThreadsLoading } = useThreads();

  useEffect(() => {
    if (typeof window === "undefined") return;

    setThreadsLoading(true);
    getThreads()
      .then(setThreads)
      .catch(console.error)
      .finally(() => setThreadsLoading(false));
  }, [getThreads, setThreads, setThreadsLoading]);

  return (
    <>
      <div className="shadow-inner-right border-border bg-muted/30 hidden h-dvh w-[300px] shrink-0 flex-col items-start justify-start gap-4 border-r lg:flex">
        <div className="flex w-full items-center justify-between px-3 pt-2">
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
          <h1 className="text-lg font-semibold tracking-tight">会话</h1>
        </div>
        <Button
          className="mx-3 w-[calc(100%-1.5rem)] justify-start gap-2"
          variant="outline"
          onClick={() => {
            void setThreadId(null);
          }}
        >
          <MessageSquarePlus className="size-4" /> 新建会话
        </Button>
        <ThreadList threads={threads} />
      </div>
      <div className="lg:hidden">
        <Sheet
          open={!!chatHistoryOpen && !isLargeScreen}
          onOpenChange={(open) => {
            if (isLargeScreen) return;
            setChatHistoryOpen(open);
          }}
        >
          <SheetContent
            side="left"
            className="flex lg:hidden"
          >
            <SheetHeader>
              <SheetTitle>会话</SheetTitle>
            </SheetHeader>
            <ThreadList
              threads={threads}
              onThreadClick={() => setChatHistoryOpen((o) => !o)}
            />
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
