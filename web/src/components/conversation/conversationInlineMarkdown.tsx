import React, { type ReactNode } from "react";

import {
  conversationImageDownloadName,
  isLikelyConversationImageUrl,
} from "./conversationImagePreview";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";

export type ConversationInlineMarkdownClassNames = {
  inlineCode: string;
  inlineLink: string;
  inlineStrong: string;
};

export function renderConversationInlineMarkdown(
  content: string,
  classNames: ConversationInlineMarkdownClassNames,
  partIndex: number | string = "inline",
): ReactNode {
  const nodes: ReactNode[] = [];
  const inlinePattern = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|(\*\*|__)(?=\S)([\s\S]*?\S)\4/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = inlinePattern.exec(content)) !== null) {
    if (match.index > cursor) {
      nodes.push(content.slice(cursor, match.index));
    }
    if (match[1]) {
      nodes.push(
        <code key={`code-${partIndex}-${match.index}`} className={classNames.inlineCode}>
          {match[1]}
        </code>,
      );
    } else if (match[2] && match[3]) {
      const label = match[2];
      const href = match[3];
      const safeHref = safeConversationMarkdownUrl(href);
      if (safeHref) {
        nodes.push(
          <a
            key={`link-${partIndex}-${match.index}`}
            className={classNames.inlineLink}
            href={safeHref}
            download={
              isLikelyConversationImageUrl(safeHref) ? conversationImageDownloadName(safeHref) || true : undefined
            }
          >
            {label}
          </a>,
        );
      } else {
        nodes.push(label);
      }
    } else {
      const strongContent = match[5] ?? "";
      nodes.push(
        <strong key={`strong-${partIndex}-${match.index}`} className={classNames.inlineStrong}>
          {renderConversationInlineMarkdown(strongContent, classNames, `${partIndex}-strong-${match.index}`)}
        </strong>,
      );
    }
    cursor = match.index + match[0].length;
    if (match[2] && match[3] && !safeConversationMarkdownUrl(match[3]) && content[cursor] === ")") {
      cursor += 1;
    }
  }
  if (cursor < content.length) {
    nodes.push(content.slice(cursor));
  }
  return nodes.length > 0 ? nodes : content;
}
