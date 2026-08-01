"use client";

import { lazy, memo, Suspense } from "react";

const MarkdownRenderer = lazy(() =>
  import("./markdown-renderer").then((module) => ({
    default: module.MarkdownRenderer,
  })),
);

/** Load Markdown, KaTeX, and syntax highlighting only when a message needs it. */
function MarkdownTextImpl({ children }: { children: string }) {
  return (
    <Suspense
      fallback={<span className="whitespace-pre-wrap">{children}</span>}
    >
      <MarkdownRenderer>{children}</MarkdownRenderer>
    </Suspense>
  );
}

export const MarkdownText = memo(MarkdownTextImpl);
