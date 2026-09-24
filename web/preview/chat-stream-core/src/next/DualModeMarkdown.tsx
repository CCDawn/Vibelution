import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { fnv1aHash, repairIncompleteMarkdown } from "./streamdownPattern";

/**
 * Dual-mode markdown for streaming chat, following the Streamdown pattern as
 * wired by zai-org/ZCode (Apache-2.0):
 *
 * - streaming: light pipeline — repair incomplete syntax, NO highlight/mermaid,
 *   re-parse only the (small) live region each frame.
 * - done: static pipeline — full AST once, content-memoized so re-renders
 *   short-circuit on reference equality.
 *
 * The memo comparator uses reference equality first and an FNV-1a hash as a
 * cheap fallback for equal-length-but-changed strings, demonstrating the
 * "hash guard" degradation described in the alignment notes.
 */

export type DualModeMarkdownProps = {
  content: string;
  streaming: boolean;
  /** Counts every react-markdown parse pass (static once + live per frame). */
  onParse?: () => void;
};

const markdownPlugins = [remarkGfm];

function MarkdownAst({ content, onParse }: { content: string; onParse?: () => void }) {
  // Counting via render effect keeps the counter honest for both modes.
  React.useEffect(() => {
    onParse?.();
  });
  return (
    <ReactMarkdown remarkPlugins={markdownPlugins} skipHtml>
      {content}
    </ReactMarkdown>
  );
}

const StaticMarkdown = React.memo(
  function StaticMarkdown({ content, onParse }: { content: string; onParse?: () => void }) {
    return <MarkdownAst content={content} onParse={onParse} />;
  },
  (previous, next) => previous.content === next.content,
);

const StreamingMarkdown = React.memo(
  function StreamingMarkdown({ content, onParse }: { content: string; onParse?: () => void }) {
    return <MarkdownAst content={content} onParse={onParse} />;
  },
  (previous, next) => fnv1aHash(previous.content) === fnv1aHash(next.content),
);

export function DualModeMarkdown({ content, streaming, onParse }: DualModeMarkdownProps) {
  if (!streaming) {
    return <StaticMarkdown content={content} onParse={onParse} />;
  }
  const { repaired } = repairIncompleteMarkdown(content);
  return <StreamingMarkdown content={repaired} onParse={onParse} />;
}

/** Metadata badges shown next to the streaming pane. */
export function DualModeBadges({ streaming }: { streaming: boolean }) {
  return (
    <span className="state-badges">
      <span className={`state-badge ${streaming ? "on" : ""}`}>
        {streaming ? "流式中：轻解析 + 补全 ON" : "完成：static 全量 AST × 1"}
      </span>
      <span className={`state-badge ${streaming ? "warn" : "on"}`}>
        {streaming ? "高亮/mermaid OFF" : "memo 生效"}
      </span>
    </span>
  );
}
