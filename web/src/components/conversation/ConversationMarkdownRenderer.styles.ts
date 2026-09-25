import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import conversationViewStyles from "./ConversationView.styles";

/**
 * Overflow disclosure for the completed-path render budget (oversized code
 * blocks and tables fold behind a native `<details>`, mirroring the
 * ConversationPatchDiff expansion interaction).
 */
export const conversationMarkdownOverflowStyles = {
  overflowDetails: "vui-components-conversationview markdownOverflowDetails min-w-0 max-w-full",
  overflowSummary:
    "vui-components-conversationview markdownOverflowSummary flex w-full list-none cursor-pointer items-center gap-x-1.5 py-1 text-left [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none hover:text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
} as const;

export const conversationMarkdownRendererStyles: ConversationMarkdownClassNames = {
  inlineCode: conversationViewStyles.inlineCode,
  inlineLink: conversationViewStyles.inlineLink,
  inlineStrong: conversationViewStyles.inlineStrong,
  markdownBlockquote: conversationViewStyles.markdownBlockquote,
  markdownBody: conversationViewStyles.markdownBody,
  markdownBodyWithTable: conversationViewStyles.markdownBodyWithTable,
  markdownDivider: conversationViewStyles.markdownDivider,
  markdownHeading: conversationViewStyles.markdownHeading,
  markdownHeading1: conversationViewStyles.markdownHeading1,
  markdownHeading2: conversationViewStyles.markdownHeading2,
  markdownHeading3: conversationViewStyles.markdownHeading3,
  markdownHeading4: conversationViewStyles.markdownHeading4,
  markdownTable: conversationViewStyles.markdownTable,
  markdownTableWrap: conversationViewStyles.markdownTableWrap,
  messageBody: conversationViewStyles.messageBody,
  responseSegmentList: conversationViewStyles.responseSegmentList,
  responseSegmentPre: conversationViewStyles.responseSegmentPre,
};
