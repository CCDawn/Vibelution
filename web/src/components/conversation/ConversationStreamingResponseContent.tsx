import React, { ReactNode, useMemo } from "react";

import type { MarkdownBlock } from "./conversationMarkdownBlocks";
import { projectStreamingMarkdownBlocks } from "./streamingMarkdown";

export type ConversationStreamingResponseContentClassNames = {
  markdownBody: string;
  streamingResponseText: string;
  markdownBodyWithTable: string;
};

type ConversationStreamingResponseContentProps = {
  content: string;
  classNames: ConversationStreamingResponseContentClassNames;
  renderBlock: (block: MarkdownBlock, index: number) => ReactNode;
};

export function ConversationStreamingResponseContent({
  content,
  classNames,
  renderBlock,
}: ConversationStreamingResponseContentProps) {
  const visibleText = String(content ?? "");
  const markdownProjection = useMemo(() => projectStreamingMarkdownBlocks(visibleText), [visibleText]);
  const blocks = markdownProjection.blocks;
  const hasTable = blocks.some((block) => block.type === "table");

  if (!visibleText || blocks.length === 0) {
    return null;
  }

  return (
    <div
      className={[
        classNames.markdownBody,
        classNames.streamingResponseText,
        hasTable ? classNames.markdownBodyWithTable : "",
      ].filter(Boolean).join(" ")}
    >
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
}
