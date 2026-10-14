/**
 * One markdown table row somewhere in the content (`| … |` line). Shared so
 * non-renderer call sites (e.g. group-message collapse heuristics) stay in
 * sync with what the renderer actually treats as a table.
 */
export const CONVERSATION_MARKDOWN_TABLE_PATTERN = /^\s*\|.+\|\s*$/m;

/**
 * Tables at or beyond this many columns switch to the dense variant (tighter
 * cell padding, smaller type) so their horizontal overflow stays navigable.
 */
export const CONVERSATION_MARKDOWN_DENSE_TABLE_MIN_COLUMNS = 6;

export type ConversationMarkdownClassNames = {
  inlineCode: string;
  inlineLink: string;
  inlineStrong: string;
  markdownBlockquote: string;
  markdownBody: string;
  markdownBodyWithTable: string;
  markdownDivider: string;
  markdownHeading: string;
  markdownHeading1: string;
  markdownHeading2: string;
  markdownHeading3: string;
  markdownHeading4: string;
  markdownTable: string;
  markdownTableWrap: string;
  /**
   * Optional extras for wide tables (≥ CONVERSATION_MARKDOWN_DENSE_TABLE_MIN_COLUMNS
   * columns): tighter cell padding/smaller type, plus a scroll-hint caption.
   * Optional because host style maps and test fakes predate them.
   */
  markdownTableDense?: string;
  markdownTableScrollHint?: string;
  messageBody: string;
  responseSegmentList: string;
  responseSegmentPre: string;
};
