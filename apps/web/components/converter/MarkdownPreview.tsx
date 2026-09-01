"use client";

import { useMemo } from "react";

import { renderMarkdown } from "@/lib/sanitize";

/**
 * Rendered Markdown, laid out for reading.
 *
 * The HTML inserted here comes from `renderMarkdown`, which parses the
 * Markdown and then runs the result through DOMPurify against an allowlist.
 * `dangerouslySetInnerHTML` is only ever handed sanitized output - converted
 * documents are untrusted input and can carry script payloads.
 */
export function MarkdownPreview({
  markdown,
  compact = false,
}: {
  markdown: string;
  compact?: boolean;
}) {
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);

  if (!markdown.trim()) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        This file produced no readable content.
      </p>
    );
  }

  return (
    <div
      className={compact ? "reading reading-compact" : "reading"}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
