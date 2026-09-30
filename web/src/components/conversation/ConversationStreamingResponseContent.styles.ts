import { conversationMarkdownRendererStyles } from "./ConversationMarkdownRenderer.styles";

// This surface survives the streaming-to-settled transition. Keep the full
// Markdown presentation shared; only streaming layout belongs here.
const styles = {
  ...conversationMarkdownRendererStyles,
  streamingResponseText:
    "vui-components-conversationview streamingResponseText min-w-0 max-w-full whitespace-normal break-words [overflow-wrap:anywhere]",
  streamingLiveTail:
    "vui-components-conversationview streamingLiveTail min-w-0 mt-3 first:mt-0 text-vui-sm leading-[1.8] text-[var(--fg-primary)]",
} as const;

export default styles;
