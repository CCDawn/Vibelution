import React, { useMemo } from "react";

import { createCodexStreamController } from "./codexStreamController";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import styles from "./ConversationStreamingResponseContent.styles";
import { projectStreamingMarkdownBlocks } from "./streamingMarkdown";

export type ConversationStreamingResponseContentClassNames = ConversationMarkdownClassNames & {
  streamingResponseText: string;
};

type ConversationStreamingResponseContentProps = {
  content: string;
  classNames?: ConversationStreamingResponseContentClassNames;
};

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
  const renderText = [streamProjection.stableText, streamProjection.liveText].filter(Boolean).join("\n\n") || visibleText;
  const hasTable = /^\s*\|.+\|\s*$/m.test(renderText);

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
      <LazyConversationMarkdownRenderer content={renderText} classNames={classNames} />
    </div>
  );
}
