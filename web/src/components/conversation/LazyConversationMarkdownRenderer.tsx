import { lazy, Suspense, type ReactNode } from "react";

import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import styles from "./LazyConversationMarkdownRenderer.styles";

export type LazyConversationMarkdownRendererProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => ReactNode;
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
 */
export function LazyConversationMarkdownRenderer(props: LazyConversationMarkdownRendererProps) {
  return (
    <Suspense fallback={<MarkdownFallback content={props.content} classNames={props.classNames} />}>
      <ConversationMarkdownRenderer {...props} />
    </Suspense>
  );
}
