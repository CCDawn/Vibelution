import React, { ReactNode, useMemo, useRef } from "react";

import type { MarkdownBlock } from "./conversationMarkdownBlocks";
import { createCodexStreamController } from "./codexStreamController";
import styles from "./ConversationStreamingResponseContent.styles";
import { parseStreamingMarkdownBlocks, projectStreamingMarkdownBlocks } from "./streamingMarkdown";

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
  const streamProjection = useMemo(() => {
    const controller = createCodexStreamController();
    controller.push(visibleText);
    const snapshot = controller.snapshot();
    const stableText = snapshot.queuedStableText || snapshot.emittedStableText;
    const liveText = snapshot.liveTailText;
    if (!stableText && !liveText) {
      return projectStreamingMarkdownBlocks(visibleText);
    }
    return {
      stableText,
      liveText,
    };
  }, [visibleText]);
  const markdownProjection = useMemo(() => {
    const stableBlocks = streamProjection.stableText
      ? parseStreamingMarkdownBlocks(streamProjection.stableText)
      : [];
    const liveBlocks = streamProjection.liveText
      ? parseStreamingMarkdownBlocks(streamProjection.liveText)
      : [];
    return {
      stableText: streamProjection.stableText,
      liveText: streamProjection.liveText,
      stableBlocks,
      liveBlocks,
      blocks: [...stableBlocks, ...liveBlocks],
    };
  }, [streamProjection]);
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
