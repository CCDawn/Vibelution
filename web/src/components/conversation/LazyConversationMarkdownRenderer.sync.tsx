/**
 * Test-only sync shim so renderToStaticMarkup exercises full markdown sanitization.
 * Production builds use LazyConversationMarkdownRenderer.tsx with React.lazy.
 */
export {
  ConversationMarkdownRenderer as LazyConversationMarkdownRenderer,
} from "./ConversationMarkdownRenderer";
export type {
  ConversationMarkdownRendererProps as LazyConversationMarkdownRendererProps,
} from "./ConversationMarkdownRenderer";
