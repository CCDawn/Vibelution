import React, { ReactNode, useMemo, useRef } from "react";

import type { MarkdownBlock } from "./conversationMarkdownBlocks";
import styles from "./ConversationStreamingResponseContent.styles";
import { projectStreamingMarkdownBlocks } from "./streamingMarkdown";

export type ConversationStreamingResponseContentClassNames = {
  markdownBody: string;
  streamingResponseText: string;
  markdownBodyWithTable: string;
};

type ConversationStreamingResponseContentProps = {
  content: string;
  classNames?: ConversationStreamingResponseContentClassNames;
  renderBlock: (block: MarkdownBlock, index: number) => ReactNode;
};

type StreamingMarkdownBlockRendererRef = {
  current: (block: MarkdownBlock, index: number) => ReactNode;
};

type StableStreamingMarkdownBlocksProps = {
  stableText: string;
  blocks: MarkdownBlock[];
  renderBlockRef: StreamingMarkdownBlockRendererRef;
};

type LiveStreamingMarkdownBlocksProps = {
  blocks: MarkdownBlock[];
  startIndex: number;
  renderBlock: (block: MarkdownBlock, index: number) => ReactNode;
};

const StableStreamingMarkdownBlocks = React.memo(function StableStreamingMarkdownBlocks({
  blocks,
  renderBlockRef,
}: StableStreamingMarkdownBlocksProps) {
  if (blocks.length === 0) {
    return null;
  }
  return <>{blocks.map((block, index) => renderBlockRef.current(block, index))}</>;
}, stableStreamingMarkdownBlocksPropsAreEqual);

function stableStreamingMarkdownBlocksPropsAreEqual(
  previous: StableStreamingMarkdownBlocksProps,
  next: StableStreamingMarkdownBlocksProps,
) {
  return previous.stableText === next.stableText
    && previous.blocks === next.blocks
    && previous.renderBlockRef === next.renderBlockRef;
}

function LiveStreamingMarkdownBlocks({
  blocks,
  startIndex,
  renderBlock,
}: LiveStreamingMarkdownBlocksProps) {
  if (blocks.length === 0) {
    return null;
  }
  return <>{blocks.map((block, index) => renderBlock(block, startIndex + index))}</>;
}

export function ConversationStreamingResponseContent({
  content,
  classNames = styles,
  renderBlock,
}: ConversationStreamingResponseContentProps) {
  const visibleText = String(content ?? "");
  const markdownProjection = useMemo(() => projectStreamingMarkdownBlocks(visibleText), [visibleText]);
  const renderBlockRef = useRef(renderBlock);
  renderBlockRef.current = renderBlock;
  const hasBlocks = markdownProjection.stableBlocks.length > 0 || markdownProjection.liveBlocks.length > 0;
  const hasTable = markdownProjection.stableBlocks.some((block) => block.type === "table")
    || markdownProjection.liveBlocks.some((block) => block.type === "table");

  if (!visibleText || !hasBlocks) {
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
      <StableStreamingMarkdownBlocks
        stableText={markdownProjection.stableText}
        blocks={markdownProjection.stableBlocks}
        renderBlockRef={renderBlockRef}
      />
      <LiveStreamingMarkdownBlocks
        blocks={markdownProjection.liveBlocks}
        startIndex={markdownProjection.stableBlocks.length}
        renderBlock={renderBlock}
      />
    </div>
  );
}
