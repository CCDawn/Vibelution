import { lazy, Suspense, type ReactNode } from "react";

import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import { ConversationMarkdownErrorBoundary } from "./LazyConversationMarkdownRenderer.errorBoundary";
import styles from "./LazyConversationMarkdownRenderer.styles";

export type LazyConversationMarkdownRendererProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => ReactNode;
  /** Session workspace root enabling workspace-file markdown links. */
  workspaceRoot?: string;
  /** Bilingual chrome text for workspace-file menus and mermaid blocks. */
  language?: "zh" | "en";
};

const ConversationMarkdownRenderer = lazy(async () => {
  const module = await import("./ConversationMarkdownRenderer");
  return { default: module.ConversationMarkdownRenderer };
});

function MarkdownFallback({
  content,
  classNames,
}: {
  content: string;
  classNames?: ConversationMarkdownClassNames;
}) {
  const text = String(content ?? "");
  if (!text.trim()) {
    return null;
  }
  // Avoid importing ConversationView.styles here — that would re-couple the shell chunk.
  if (classNames?.markdownBody) {
    return (
      <div className={classNames.markdownBody}>
        <p className={`${classNames.messageBody} ${styles.fallbackText}`}>{text}</p>
      </div>
    );
  }
  return <pre className={styles.fallbackPre}>{text}</pre>;
}

/**
 * Loads react-markdown / remark-gfm only when conversation content needs rich rendering.
 * Keeps the ConversationView feature chunk free of the markdown dependency graph.
 * A render crash inside one markdown block degrades to the boundary's raw-text
 * fallback instead of blanking the stream.
 */
export function LazyConversationMarkdownRenderer(props: LazyConversationMarkdownRendererProps) {
  return (
    <ConversationMarkdownErrorBoundary content={props.content} classNames={props.classNames}>
      <Suspense fallback={<MarkdownFallback content={props.content} classNames={props.classNames} />}>
        <ConversationMarkdownRenderer {...props} />
      </Suspense>
    </ConversationMarkdownErrorBoundary>
  );
}
