import {
  parseStreamingMarkdownBlocks,
  type MarkdownBlock,
} from "./streamingMarkdown";

export type { MarkdownBlock };

export function parseConversationMarkdownBlocks(content: string): MarkdownBlock[] {
  return parseStreamingMarkdownBlocks(content);
}
