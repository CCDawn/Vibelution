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
    "vui-components-conversationview markdownOverflowSummary flex w-full list-none cursor-pointer items-center gap-x-1.5 py-1 text-left text-vui-xs text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none hover:text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
} as const;

/**
 * Completed code blocks render behind a header bar (ZCode CodeBlockHeader
 * alignment): language label at the left, soft-wrap toggle and copy control at
 * the right. The header attaches to the host-provided `responseSegmentPre`
 * chrome (border/rounding comes from the owning style map, so no second card
 * system is introduced here) — `preAttached` only neutralizes the pre's own
 * top margin/border/rounding so header + pre read as one block.
 */
export const conversationMarkdownCodeBlockStyles = {
  shell: "vui-components-conversationview markdownCodeBlock min-w-0 max-w-full",
  header:
    "vui-components-conversationview markdownCodeBlockHeader mt-4 flex min-h-10 min-w-0 max-w-full items-center justify-between gap-x-2 rounded-t-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-3 py-1",
  language:
    "vui-components-conversationview markdownCodeBlockLanguage min-w-0 truncate font-mono lowercase text-vui-2xs text-[var(--fg-tertiary)]",
  actions: "vui-components-conversationview markdownCodeBlockActions inline-flex shrink-0 items-center gap-x-0.5",
  headerButton:
    "vui-components-conversationview markdownCodeBlockHeaderButton inline-grid h-6 w-6 place-items-center border-0 bg-transparent p-0 text-[var(--fg-tertiary)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)]",
  headerButtonActive:
    "vui-components-conversationview markdownCodeBlockHeaderButtonActive text-[var(--accent-cool)] hover:text-[var(--accent-cool)]",
  // Explicit overrides keep the seam joined even when production CSS chunk
  // order places the host's border/radius shorthand after this style map.
  preAttached:
    "vui-components-conversationview markdownCodeBlockPre mt-0 !rounded-t-none !border-t-0",
  preWrapped:
    "vui-components-conversationview markdownCodeBlockPreWrapped whitespace-pre-wrap break-words",
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
