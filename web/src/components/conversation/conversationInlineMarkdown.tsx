import React, { type ReactNode } from "react";

import {
  conversationImageDownloadName,
  isLikelyConversationImageUrl,
} from "./conversationImagePreview";
import { classifyConversationMarkdownLinkTarget } from "./conversationMarkdownLinkTargets";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";
import { ConversationMarkdownWorkspaceFileLink } from "./conversationMarkdownWorkspaceFileLink";
import styles from "./conversationInlineMarkdown.styles";

export type ConversationInlineMarkdownClassNames = {
  inlineCode: string;
  inlineLink: string;
  inlineStrong: string;
};

/** Present only on the streaming live tail. Group transcripts omit it. */
export type ConversationInlineLinkContext = {
  workspaceRoot?: string;
  language?: "zh" | "en";
  onOpenRailFile?: (path: string) => void;
};

export function renderConversationInlineMarkdown(
  content: string,
  classNames: ConversationInlineMarkdownClassNames = styles,
  partIndex: number | string = "inline",
  context?: ConversationInlineLinkContext,
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
      const workspaceFile = context
        ? classifyConversationMarkdownLinkTarget(href, context.workspaceRoot)
        : null;
      if (workspaceFile?.kind === "workspace-file") {
        nodes.push(
          <ConversationMarkdownWorkspaceFileLink
            key={`file-${partIndex}-${match.index}`}
            path={workspaceFile.absolutePath}
            className={classNames.inlineLink}
            language={context?.language ?? "zh"}
            onOpenInRail={context?.onOpenRailFile}
          >
            {label}
          </ConversationMarkdownWorkspaceFileLink>,
        );
      } else if (safeHref) {
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
          {renderConversationInlineMarkdown(strongContent, classNames, `${partIndex}-strong-${match.index}`, context)}
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
