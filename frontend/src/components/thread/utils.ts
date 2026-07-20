import type { BaseMessage } from "@langchain/core/messages";

function readImageUrl(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return undefined;

  const record = value as Record<string, unknown>;
  return typeof record.url === "string" ? record.url : undefined;
}

function contentBlockToText(block: unknown): string {
  if (block == null) return "";
  if (typeof block === "string") return block;
  if (typeof block !== "object") return String(block);

  const record = block as Record<string, unknown>;
  if (typeof record.text === "string") return record.text;
  if (typeof record.markdown === "string") return record.markdown;

  const imageUrl =
    readImageUrl(record.image_url) ??
    readImageUrl(record.imageUrl) ??
    readImageUrl(record.url);
  if (imageUrl) return `![生成图片](${imageUrl})`;

  return "";
}

/**
 * Extracts a string summary from a message's content, supporting multimodal (text, image, file, etc.).
 * - If text is present, returns the joined text.
 * - If not, returns a label for the first non-text modality (e.g., 'Image', 'Other').
 * - If unknown, returns 'Multimodal message'.
 */
export function getContentString(
  content: BaseMessage["content"] | unknown,
): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map(contentBlockToText).filter(Boolean).join("\n\n");
  }
  if (typeof content === "object") {
    const text = contentBlockToText(content);
    if (text) return text;

    try {
      return JSON.stringify(content, null, 2);
    } catch {
      return String(content);
    }
  }
  return String(content);
}
