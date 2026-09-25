import { memo, useMemo, type ReactNode } from "react";

import { createCodexStreamController } from "./codexStreamController";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import { StreamingLiveMarkdownBlocks } from "./StreamingLiveMarkdownBlocks";
import styles from "./ConversationStreamingResponseContent.styles";
import {
  parseStreamingMarkdownBlocks,
  projectStreamingMarkdownBlocks,
} from "./streamingMarkdown";
import { repairIncompleteMarkdown } from "./streamingIncompleteMarkdown";

export type ConversationStreamingResponseContentClassNames = ConversationMarkdownClassNames & {
  streamingResponseText: string;
  streamingLiveTail?: string;
};

type ConversationStreamingResponseContentProps = {
  content: string;
  /**
   * Single render surface for assistant transcript markdown: the streaming
   * phase keeps the Codex stable/live split, settled mode renders the full
   * text through the same shared stable renderer so the streaming→settled
   * flip never unmounts the markdown subtree (pattern: zai-org/ZCode message
   * renderer keying, Apache-2.0).
   */
  isStreaming?: boolean;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => ReactNode;
  classNames?: ConversationStreamingResponseContentClassNames;
};

/**
 * Memoized stable prefix: ChatGPT/Cursor-style streaming keeps completed
 * markdown DOM warm while only the live tail updates each frame.
 */
const StreamingStableMarkdown = memo(function StreamingStableMarkdown({
  content,
  classNames,
  duplicateImageUrls,
  renderImage,
}: {
  content: string;
  classNames: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => ReactNode;
}) {
  return (
    <LazyConversationMarkdownRenderer
      content={content}
      classNames={classNames}
      duplicateImageUrls={duplicateImageUrls}
      renderImage={renderImage}
    />
  );
});

export function ConversationStreamingResponseContent({
  content,
  isStreaming = true,
  duplicateImageUrls,
  renderImage,
  classNames = styles,
}: ConversationStreamingResponseContentProps) {
  const visibleText = String(content ?? "");
  const streamProjection = useMemo(() => {
    if (!isStreaming) {
      // Settled: the whole message goes through the shared stable renderer —
      // no Codex holdback split, no live tail, no incomplete-markdown repair.
      return { stableText: visibleText, liveText: "" };
    }
    const controller = createCodexStreamController();
    controller.push(visibleText);
    const snapshot = controller.snapshot();
    const stableText = snapshot.queuedStableText || snapshot.emittedStableText;
    const liveText = snapshot.liveTailText;
    if (!stableText && !liveText) {
      return projectStreamingMarkdownBlocks(visibleText);
    }
    return { stableText, liveText };
  }, [visibleText, isStreaming]);

  const hasStable = Boolean(streamProjection.stableText?.trim());
  const hasLive = Boolean(streamProjection.liveText);
  // When the controller has not split yet, fall back to full stable markdown.
  const stableText = hasStable
    ? streamProjection.stableText
    : hasLive
      ? ""
      : visibleText;
  const liveText = hasStable || hasLive ? (streamProjection.liveText || "") : "";
  // Dual-mode live tail (pattern: vercel/streamdown + zai-org/ZCode,
  // Apache-2.0): repair incomplete syntax, then parse with the line-level
  // block projector. No react-markdown AST pass, no highlighting — only this
  // bounded subtree re-parses per frame.
  const liveBlocks = useMemo(
    () => (liveText ? parseStreamingMarkdownBlocks(repairIncompleteMarkdown(liveText).repaired) : []),
    [liveText],
  );
  const hasTable = /^\s*\|.+\|\s*$/m.test(stableText) || liveBlocks.some((block) => block.type === "table");

  if (!visibleText.trim()) {
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
      {stableText.trim() ? (
        <StreamingStableMarkdown
          content={stableText}
          classNames={classNames}
          duplicateImageUrls={duplicateImageUrls}
          renderImage={renderImage}
        />
      ) : null}
      {liveBlocks.length ? (
        <div
          className={classNames.streamingLiveTail || styles.streamingLiveTail}
          data-streaming-live-tail="1"
        >
          {/*
            Live tail is a separate light-parsed instance so only this subtree
            does per-frame work (Cursor/ChatGPT-style stable+live split).
            Incomplete open fences/tables are repaired then held here by design.
          */}
          <StreamingLiveMarkdownBlocks blocks={liveBlocks} classNames={classNames} />
        </div>
      ) : null}
    </div>
  );
}
