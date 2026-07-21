import { ContentBlock } from "@langchain/core/messages";
import { toast } from "sonner";

export type TextContentBlock = {
  type: "text";
  text: string;
  metadata?: Record<string, unknown>;
};

export type ChatContentBlock = ContentBlock.Multimodal.Data | TextContentBlock;

const SUPPORTED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
];

const SUPPORTED_DOCUMENT_TYPES = ["application/pdf"];

const SUPPORTED_TEXT_MIME_TYPES = new Set([
  "application/javascript",
  "application/json",
  "application/sql",
  "application/typescript",
  "application/x-httpd-php",
  "application/x-javascript",
  "application/x-python-code",
  "application/x-sh",
  "application/xhtml+xml",
  "application/xml",
  "text/css",
  "text/csv",
  "text/html",
  "text/javascript",
  "text/jsx",
  "text/markdown",
  "text/plain",
  "text/tsx",
  "text/typescript",
  "text/x-c",
  "text/x-c++",
  "text/x-go",
  "text/x-java-source",
  "text/x-python",
  "text/x-ruby",
  "text/x-rust",
  "text/x-scala",
  "text/x-shellscript",
  "text/xml",
  "text/yaml",
]);

const CODE_EXTENSION_LANGUAGE: Record<string, string> = {
  ".bash": "bash",
  ".c": "c",
  ".cc": "cpp",
  ".cpp": "cpp",
  ".cs": "csharp",
  ".css": "css",
  ".cxx": "cpp",
  ".go": "go",
  ".h": "c",
  ".hpp": "cpp",
  ".htm": "html",
  ".html": "html",
  ".java": "java",
  ".js": "javascript",
  ".json": "json",
  ".jsx": "jsx",
  ".kt": "kotlin",
  ".kts": "kotlin",
  ".less": "less",
  ".lua": "lua",
  ".mjs": "javascript",
  ".md": "markdown",
  ".mdx": "markdown",
  ".php": "php",
  ".proto": "protobuf",
  ".py": "python",
  ".rb": "ruby",
  ".rs": "rust",
  ".sass": "sass",
  ".scala": "scala",
  ".scss": "scss",
  ".sh": "bash",
  ".sql": "sql",
  ".swift": "swift",
  ".toml": "toml",
  ".ts": "typescript",
  ".tsx": "tsx",
  ".txt": "text",
  ".vue": "vue",
  ".xml": "xml",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".zsh": "bash",
};

const TEXT_FILE_MAX_CHARS = 60_000;
const IMAGE_MAX_EDGE_PX = 1600;
const IMAGE_OPTIMIZE_MIN_BYTES = 512 * 1024;
const IMAGE_COMPRESS_QUALITY = 0.88;

type Base64Payload = {
  data: string;
  mimeType: string;
  size: number;
  optimized: boolean;
};

export const UPLOAD_ATTACHMENT_ACCEPT = [
  ...SUPPORTED_IMAGE_TYPES,
  ...SUPPORTED_DOCUMENT_TYPES,
  ".bash",
  ".c",
  ".cc",
  ".cpp",
  ".cs",
  ".css",
  ".go",
  ".h",
  ".hpp",
  ".html",
  ".java",
  ".js",
  ".json",
  ".jsx",
  ".kt",
  ".lua",
  ".md",
  ".mdx",
  ".php",
  ".proto",
  ".py",
  ".rb",
  ".rs",
  ".scala",
  ".scss",
  ".sh",
  ".sql",
  ".swift",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".vue",
  ".xml",
  ".yaml",
  ".yml",
].join(",");

function getFileExtension(filename: string) {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}

export function inferTextFileLanguage(file: File) {
  return CODE_EXTENSION_LANGUAGE[getFileExtension(file.name)] ?? "text";
}

export function isSupportedUploadFile(file: File) {
  return (
    SUPPORTED_IMAGE_TYPES.includes(file.type) ||
    SUPPORTED_DOCUMENT_TYPES.includes(file.type) ||
    isSupportedTextFile(file)
  );
}

export function isSupportedTextFile(file: File) {
  const extension = getFileExtension(file.name);
  return (
    file.type.startsWith("text/") ||
    SUPPORTED_TEXT_MIME_TYPES.has(file.type) ||
    extension in CODE_EXTENSION_LANGUAGE
  );
}

function imageDimensions(width: number, height: number) {
  const largestEdge = Math.max(width, height);
  if (largestEdge <= IMAGE_MAX_EDGE_PX) return { width, height };

  const scale = IMAGE_MAX_EDGE_PX / largestEdge;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new window.Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("图片读取失败"));
    };
    image.src = url;
  });
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality: number,
): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

async function imageToBase64Payload(file: File): Promise<Base64Payload> {
  const original = async (): Promise<Base64Payload> => ({
    data: await fileToBase64(file),
    mimeType: file.type,
    size: file.size,
    optimized: false,
  });

  if (file.type === "image/gif") return original();

  try {
    const image = await loadImage(file);
    const { width, height } = imageDimensions(
      image.naturalWidth || image.width,
      image.naturalHeight || image.height,
    );
    const shouldResize =
      width !== (image.naturalWidth || image.width) ||
      height !== (image.naturalHeight || image.height);
    const shouldCompress = file.size >= IMAGE_OPTIMIZE_MIN_BYTES;

    if (!shouldResize && !shouldCompress) return original();

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) return original();

    context.fillStyle = "#fff";
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);

    const blob = await canvasToBlob(
      canvas,
      "image/jpeg",
      IMAGE_COMPRESS_QUALITY,
    );
    if (!blob || blob.size >= file.size) return original();

    return {
      data: await fileToBase64(blob),
      mimeType: blob.type || "image/jpeg",
      size: blob.size,
      optimized: true,
    };
  } catch {
    return original();
  }
}

function makeMarkdownCodeFence(code: string) {
  const longestFence = code
    .match(/`{3,}/g)
    ?.reduce((longest, current) => Math.max(longest, current.length), 2);
  return "`".repeat((longestFence ?? 2) + 1);
}

async function textFileToContentBlock(file: File): Promise<TextContentBlock> {
  const language = inferTextFileLanguage(file);
  const rawText = await file.text();
  const truncated = rawText.length > TEXT_FILE_MAX_CHARS;
  const text = truncated ? rawText.slice(0, TEXT_FILE_MAX_CHARS) : rawText;
  const fence = makeMarkdownCodeFence(text);
  const truncationNotice = truncated
    ? "\n\n[文件内容过长，已截取前 60000 个字符。]"
    : "";

  return {
    type: "text",
    text: `已上传代码文件：${file.name}\n\n${fence}${language}\n${text}\n${fence}${truncationNotice}`,
    metadata: {
      filename: file.name,
      mimeType: file.type || "text/plain",
      language,
      size: file.size,
      truncated,
    },
  };
}

// Returns a Promise of a typed content block for images, PDFs, or text/code files.
export async function fileToContentBlock(
  file: File,
): Promise<ChatContentBlock> {
  if (!isSupportedUploadFile(file)) {
    toast.error("不支持这种文件，请上传图片、PDF 或代码/文本文件。");
    return Promise.reject(new Error("不支持这种文件"));
  }

  if (isSupportedTextFile(file)) {
    return textFileToContentBlock(file);
  }

  if (SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    const payload = await imageToBase64Payload(file);
    return {
      type: "image",
      mimeType: payload.mimeType,
      data: payload.data,
      metadata: {
        name: file.name,
        originalMimeType: file.type,
        originalSize: file.size,
        size: payload.size,
        optimized: payload.optimized,
      },
    };
  }

  const data = await fileToBase64(file);

  // PDF
  return {
    type: "file",
    mimeType: "application/pdf",
    data,
    metadata: { filename: file.name },
  };
}

// Helper to convert File to base64 string
export async function fileToBase64(file: Blob): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      // Remove the data:...;base64, prefix
      resolve(result.split(",")[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// Type guard for Base64ContentBlock
export function isBase64ContentBlock(
  block: unknown,
): block is ContentBlock.Multimodal.Data {
  if (typeof block !== "object" || block === null || !("type" in block))
    return false;
  // file type (legacy)
  if (
    (block as { type: unknown }).type === "file" &&
    "mimeType" in block &&
    typeof (block as { mimeType?: unknown }).mimeType === "string" &&
    ((block as { mimeType: string }).mimeType.startsWith("image/") ||
      (block as { mimeType: string }).mimeType === "application/pdf")
  ) {
    return true;
  }
  // image type (new)
  if (
    (block as { type: unknown }).type === "image" &&
    "mimeType" in block &&
    typeof (block as { mimeType?: unknown }).mimeType === "string" &&
    (block as { mimeType: string }).mimeType.startsWith("image/")
  ) {
    return true;
  }
  return false;
}

export function isTextContentBlock(block: unknown): block is TextContentBlock {
  return (
    typeof block === "object" &&
    block !== null &&
    (block as { type?: unknown }).type === "text" &&
    typeof (block as { text?: unknown }).text === "string"
  );
}
