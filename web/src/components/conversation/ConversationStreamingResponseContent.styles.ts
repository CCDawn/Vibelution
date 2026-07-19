const styles = {
  inlineCode:
    "vui-components-conversationview inlineCode min-w-0 font-mono [font-size:var(--vui-font-xs)] whitespace-normal break-words",
  inlineLink:
    "vui-components-conversationview inlineLink min-w-0",
  inlineStrong:
    "vui-components-conversationview inlineStrong min-w-0",
  markdownBlockquote:
    "vui-components-conversationview markdownBlockquote min-w-0",
  markdownBody:
    "vui-components-conversationview markdownBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-[min(100%,128ch)] whitespace-normal break-words [overflow-wrap:anywhere]",
  streamingResponseText:
    "vui-components-conversationview streamingResponseText min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [font-size:var(--vui-font-chat)] leading-[var(--vui-line-readable)] whitespace-normal break-words [overflow-wrap:anywhere]",
  markdownBodyWithTable:
    "vui-components-conversationview markdownBodyWithTable min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-full",
  markdownDivider:
    "vui-components-conversationview markdownDivider min-w-0",
  markdownHeading:
    "vui-components-conversationview markdownHeading min-w-0",
  markdownHeading1:
    "vui-components-conversationview markdownHeading1 min-w-0",
  markdownHeading2:
    "vui-components-conversationview markdownHeading2 min-w-0",
  markdownHeading3:
    "vui-components-conversationview markdownHeading3 min-w-0",
  markdownHeading4:
    "vui-components-conversationview markdownHeading4 min-w-0",
  markdownTable:
    "vui-components-conversationview markdownTable min-w-full table-fixed",
  markdownTableWrap:
    "vui-components-conversationview markdownTableWrap max-w-full overflow-x-auto overflow-y-hidden [scrollbar-gutter:stable]",
  messageBody:
    "vui-components-conversationview messageBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] whitespace-pre-wrap [overflow-wrap:anywhere] max-w-[min(100%,76ch)]",
  responseSegmentList:
    "vui-components-conversationview responseSegmentList min-w-0",
  responseSegmentPre:
    "vui-components-conversationview responseSegmentPre min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]",
} as const;

export default styles;
