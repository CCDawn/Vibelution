import React, { memo, useMemo } from "react";

import { createCodexStreamController } from "./codexStreamController";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import styles from "./ConversationStreamingResponseContent.styles";
import { projectStreamingMarkdownBlocks } from "./streamingMarkdown";

export type ConversationStreamingResponseContentClassNames = ConversationMarkdownClassNames & {
  streamingResponseText: string;
  streamingLiveTail?: string;
};

type ConversationStreamingResponseContentProps = {
  content: string;
  classNames?: ConversationStreamingResponseContentClassNames;
};

/**
 * Memoized stable prefix: ChatGPT/Cursor-style streaming keeps completed
 * markdown DOM warm while only the live tail updates each frame.
 */
const StreamingStableMarkdown = memo(function StreamingStableMarkdown({
  content,
  classNames,
}: {
  content: string;
  classNames: ConversationMarkdownClassNames;
}) {
  return <LazyConversationMarkdownRenderer content={content} classNames={classNames} />;
});

export function ConversationStreamingResponseContent({
  content,
  classNames = styles,
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
    return { stableText, liveText };
  }, [visibleText]);

  const hasStable = Boolean(streamProjection.stableText?.trim());
  const hasLive = Boolean(streamProjection.liveText);
  // When the controller has not split yet, fall back to full stable markdown.
  const stableText = hasStable
    ? streamProjection.stableText
    : hasLive
      ? ""
      : visibleText;
  const liveText = hasStable || hasLive ? (streamProjection.liveText || "") : "";
  const hasTable = /^\s*\|.+\|\s*$/m.test(stableText) || /^\s*\|.+\|\s*$/m.test(liveText);

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
        <StreamingStableMarkdown content={stableText} classNames={classNames} />
      ) : null}
      {liveText ? (
        <div
          className={classNames.streamingLiveTail || styles.streamingLiveTail}
          data-streaming-live-tail="1"
        >
          {/*
            Live tail is a separate markdown instance so only this subtree
            re-parses each frame (Cursor/ChatGPT-style stable+live split).
            Incomplete open fences/tables stay in the live region by design
            of the Codex stream controller.
          */}
          <LazyConversationMarkdownRenderer content={liveText} classNames={classNames} />
        </div>
      ) : null}
    </div>
  );
}
