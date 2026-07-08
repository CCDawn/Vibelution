import React, { useMemo } from "react";

import { ConversationMarkdownRenderer, type ConversationMarkdownClassNames } from "./ConversationMarkdownRenderer";
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
  const markdownProjection = useMemo(() => projectStreamingMarkdownBlocks(visibleText), [visibleText]);
  const renderText = [markdownProjection.stableText, markdownProjection.liveText].filter(Boolean).join("\n\n") || visibleText;
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
      <ConversationMarkdownRenderer content={renderText} classNames={classNames} />
    </div>
  );
}
