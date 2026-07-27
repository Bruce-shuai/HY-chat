import { useState, useRef, useEffect, ChangeEvent, useCallback } from "react";
import { toast } from "sonner";
import {
  ChatContentBlock,
  fileToContentBlock,
  isImageContentBlock,
  isSupportedTextFile,
  isSupportedUploadFile,
  isTextContentBlock,
} from "@/lib/multimodal-utils";

interface UseFileUploadOptions {
  initialBlocks?: ChatContentBlock[];
  allowImages?: boolean;
  resetKey?: string | null;
}

function isDuplicateFile(
  file: File,
  blocks: ChatContentBlock[],
  allowImages: boolean,
) {
  if (file.type === "application/pdf") {
    return blocks.some(
      (block) =>
        block.type === "file" &&
        block.mimeType === "application/pdf" &&
        block.metadata?.filename === file.name,
    );
  }
  if (isSupportedTextFile(file)) {
    return blocks.some(
      (block) =>
        isTextContentBlock(block) &&
        (block.metadata?.filename === file.name ||
          block.metadata?.name === file.name),
    );
  }
  if (isSupportedUploadFile(file, allowImages)) {
    return blocks.some(
      (block) =>
        block.type === "image" &&
        block.metadata?.name === file.name &&
        block.mimeType === file.type,
    );
  }
  return false;
}

function classifyFiles(
  files: File[],
  blocks: ChatContentBlock[],
  allowImages: boolean,
) {
  const validFiles = files.filter((file) =>
    isSupportedUploadFile(file, allowImages),
  );
  return {
    invalidFiles: files.filter(
      (file) => !isSupportedUploadFile(file, allowImages),
    ),
    duplicateFiles: validFiles.filter((file) =>
      isDuplicateFile(file, blocks, allowImages),
    ),
    uniqueFiles: validFiles.filter(
      (file) => !isDuplicateFile(file, blocks, allowImages),
    ),
  };
}

export function useFileUpload({
  initialBlocks = [],
  allowImages = false,
  resetKey,
}: UseFileUploadOptions = {}) {
  const [contentBlocks, setContentBlocks] =
    useState<ChatContentBlock[]>(initialBlocks);
  const dropRef = useRef<HTMLDivElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const dragCounter = useRef(0);
  const uploadGeneration = useRef(0);
  const previousResetKey = useRef(resetKey);

  const addFiles = useCallback(
    async (files: File[], invalidFileMessage: string) => {
      if (!files.length) return;
      const generation = uploadGeneration.current;
      const { invalidFiles, duplicateFiles, uniqueFiles } = classifyFiles(
        files,
        contentBlocks,
        allowImages,
      );

      if (invalidFiles.length > 0) {
        toast.error(invalidFileMessage);
      }
      if (duplicateFiles.length > 0) {
        toast.error(
          `检测到重复文件：${duplicateFiles.map((f) => f.name).join(", ")}。同一条消息里每个文件只能上传一次。`,
        );
      }
      if (uniqueFiles.length > 0) {
        const newBlocks = await Promise.all(
          uniqueFiles.map((file) => fileToContentBlock(file, allowImages)),
        );
        if (generation !== uploadGeneration.current) return;
        setContentBlocks((prev) => [...prev, ...newBlocks]);
      }
    },
    [allowImages, contentBlocks],
  );

  useEffect(() => {
    uploadGeneration.current += 1;
  }, [allowImages]);

  useEffect(() => {
    if (Object.is(previousResetKey.current, resetKey)) return;
    previousResetKey.current = resetKey;
    uploadGeneration.current += 1;
    setContentBlocks([]);
  }, [resetKey]);

  useEffect(() => {
    if (
      allowImages ||
      !contentBlocks.some((block) => isImageContentBlock(block))
    ) {
      return;
    }
    setContentBlocks((blocks) =>
      blocks.filter((block) => !isImageContentBlock(block)),
    );
    toast.error("当前模型不支持图片，已移除待发送的图片附件。");
  }, [allowImages, contentBlocks]);

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    await addFiles(
      Array.from(e.target.files ?? []),
      "文件类型不支持。请上传 PDF 或代码/文本文件；当前模型暂不支持图片理解。",
    );
    e.target.value = "";
  };

  // Drag and drop handlers
  useEffect(() => {
    if (!dropRef.current) return;

    // Global drag events with counter for robust dragOver state
    const handleWindowDragEnter = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        dragCounter.current += 1;
        setDragOver(true);
      }
    };
    const handleWindowDragLeave = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        dragCounter.current -= 1;
        if (dragCounter.current <= 0) {
          setDragOver(false);
          dragCounter.current = 0;
        }
      }
    };
    const handleWindowDrop = async (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setDragOver(false);

      if (!e.dataTransfer) return;

      await addFiles(
        Array.from(e.dataTransfer.files),
        "文件类型不支持。请上传 PDF 或代码/文本文件；当前模型暂不支持图片理解。",
      );
    };
    const handleWindowDragEnd = (e: DragEvent) => {
      dragCounter.current = 0;
      setDragOver(false);
    };
    window.addEventListener("dragenter", handleWindowDragEnter);
    window.addEventListener("dragleave", handleWindowDragLeave);
    window.addEventListener("drop", handleWindowDrop);
    window.addEventListener("dragend", handleWindowDragEnd);

    // Prevent default browser behavior for dragover globally
    const handleWindowDragOver = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("dragover", handleWindowDragOver);

    // Remove element-specific drop event (handled globally)
    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(true);
    };
    const handleDragEnter = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(true);
    };
    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
    };
    const element = dropRef.current;
    element.addEventListener("dragover", handleDragOver);
    element.addEventListener("dragenter", handleDragEnter);
    element.addEventListener("dragleave", handleDragLeave);

    return () => {
      element.removeEventListener("dragover", handleDragOver);
      element.removeEventListener("dragenter", handleDragEnter);
      element.removeEventListener("dragleave", handleDragLeave);
      window.removeEventListener("dragenter", handleWindowDragEnter);
      window.removeEventListener("dragleave", handleWindowDragLeave);
      window.removeEventListener("drop", handleWindowDrop);
      window.removeEventListener("dragend", handleWindowDragEnd);
      window.removeEventListener("dragover", handleWindowDragOver);
      dragCounter.current = 0;
    };
  }, [addFiles]);

  const removeBlock = (idx: number) => {
    setContentBlocks((prev) => prev.filter((_, i) => i !== idx));
  };

  const resetBlocks = () => {
    uploadGeneration.current += 1;
    setContentBlocks([]);
  };

  /**
   * Handle paste event for files (images, PDFs)
   * Can be used as onPaste={handlePaste} on a textarea or input
   */
  const handlePaste = async (
    e: React.ClipboardEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) => {
    const items = e.clipboardData.items;
    if (!items) return;
    const files: File[] = [];
    for (let i = 0; i < items.length; i += 1) {
      const item = items[i];
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length === 0) {
      return;
    }
    e.preventDefault();
    await addFiles(
      files,
      "粘贴的文件类型不支持。请粘贴 PDF 或代码/文本文件；当前模型暂不支持图片理解。",
    );
  };

  return {
    contentBlocks,
    setContentBlocks,
    handleFileUpload,
    dropRef,
    removeBlock,
    resetBlocks,
    dragOver,
    handlePaste,
  };
}
