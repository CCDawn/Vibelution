/**
 * Test-only sync shim so renderToStaticMarkup exercises full markdown sanitization.
 * Production builds use LazyConversationMarkdownRenderer.tsx with React.lazy.
 * Both paths share the render-error boundary so a crashing markdown block
 * degrades identically in tests and production.
 */
import { ConversationMarkdownRenderer } from "./ConversationMarkdownRenderer";
import { ConversationMarkdownErrorBoundary } from "./LazyConversationMarkdownRenderer.errorBoundary";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import type { ReactNode } from "react";

export type LazyConversationMarkdownRendererProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => ReactNode;
};

export function LazyConversationMarkdownRenderer(props: LazyConversationMarkdownRendererProps) {
  return (
    <ConversationMarkdownErrorBoundary content={props.content} classNames={props.classNames}>
      <ConversationMarkdownRenderer {...props} />
    </ConversationMarkdownErrorBoundary>
  );
}
