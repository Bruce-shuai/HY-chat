import React from "react";
import { Code2, File, X as XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import Image from "next/image";
import { ChatContentBlock, isTextContentBlock } from "@/lib/multimodal-utils";

export interface MultimodalPreviewProps {
  block: ChatContentBlock;
  removable?: boolean;
  onRemove?: () => void;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export const MultimodalPreview = React.memo(function MultimodalPreview({
  block,
  removable = false,
  onRemove,
  className,
  size = "md",
}: MultimodalPreviewProps) {
  if (isTextContentBlock(block)) {
    const filename =
      block.metadata?.filename || block.metadata?.name || "代码或文本文件";
    const language = block.metadata?.language;
    return (
      <div
        className={cn(
          "bg-muted relative flex max-w-80 items-start gap-2 rounded-md border px-3 py-2",
          className,
        )}
      >
        <Code2
          className={cn(
            "flex-shrink-0 text-teal-700",
            size === "sm" ? "h-5 w-5" : "h-7 w-7",
          )}
        />
        <div className="min-w-0 flex-1">
          <span className="text-foreground block truncate text-sm">
            {String(filename)}
          </span>
          {language ? (
            <span className="text-muted-foreground text-xs">
              {String(language)}
            </span>
          ) : null}
        </div>
        {removable && (
          <button
            type="button"
            className="bg-muted hover:bg-border ml-2 self-start rounded-full p-1 text-teal-700"
            onClick={onRemove}
            aria-label="移除代码文件"
          >
            <XIcon className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }

  // Image block
  if (
    block.type === "image" &&
    typeof block.mimeType === "string" &&
    block.mimeType.startsWith("image/")
  ) {
    const url = `data:${block.mimeType};base64,${block.data}`;
    let imgClass: string = "rounded-md object-cover h-16 w-16 text-lg";
    if (size === "sm") imgClass = "rounded-md object-cover h-10 w-10 text-base";
    if (size === "lg") imgClass = "rounded-md object-cover h-24 w-24 text-xl";
    return (
      <div className={cn("relative inline-block", className)}>
        <Image
          src={url}
          alt={String(block.metadata?.name || "已上传图片")}
          className={imgClass}
          width={size === "sm" ? 16 : size === "md" ? 32 : 48}
          height={size === "sm" ? 16 : size === "md" ? 32 : 48}
        />
        {removable && (
          <button
            type="button"
            className="bg-muted-foreground text-background hover:bg-foreground absolute top-1 right-1 z-10 rounded-full"
            onClick={onRemove}
            aria-label="移除图片"
          >
            <XIcon className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }

  // PDF block
  if (block.type === "file" && block.mimeType === "application/pdf") {
    const filename =
      block.metadata?.filename || block.metadata?.name || "文档文件";
    return (
      <div
        className={cn(
          "bg-muted relative flex items-start gap-2 rounded-md border px-3 py-2",
          className,
        )}
      >
        <div className="flex flex-shrink-0 flex-col items-start justify-start">
          <File
            className={cn(
              "text-teal-700",
              size === "sm" ? "h-5 w-5" : "h-7 w-7",
            )}
          />
        </div>
        <span
          className={cn("text-foreground min-w-0 flex-1 text-sm break-all")}
          style={{ wordBreak: "break-all", whiteSpace: "pre-wrap" }}
        >
          {String(filename)}
        </span>
        {removable && (
          <button
            type="button"
            className="bg-muted hover:bg-border ml-2 self-start rounded-full p-1 text-teal-700"
            onClick={onRemove}
            aria-label="移除文档"
          >
            <XIcon className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }

  // Fallback for unknown types
  return (
    <div
      className={cn(
        "bg-muted text-muted-foreground flex items-center gap-2 rounded-md border px-3 py-2",
        className,
      )}
    >
      <File className="h-5 w-5 flex-shrink-0" />
      <span className="truncate text-xs">不支持的文件类型</span>
      {removable && (
        <button
          type="button"
          className="bg-muted text-muted-foreground hover:bg-border ml-2 rounded-full p-1"
          onClick={onRemove}
          aria-label="移除文件"
        >
          <XIcon className="h-4 w-4" />
        </button>
      )}
    </div>
  );
});
