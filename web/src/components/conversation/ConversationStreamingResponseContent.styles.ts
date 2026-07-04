const styles = {
  markdownBody:
    "vui-components-conversationview markdownBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-[min(100%,76ch)]",
  streamingResponseText:
    "vui-components-conversationview streamingResponseText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] text-[var(--vui-font-chat)] leading-[var(--vui-line-readable)]",
  markdownBodyWithTable:
    "vui-components-conversationview markdownBodyWithTable min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-full",
} as const;

export default styles;
