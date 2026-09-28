// Inline tokens mirror the settled conversation markdown styles
// (ConversationView.styles inlineCode/inlineLink/inlineStrong) so the light
// live-tail renderer never owns a second visual language: streaming pills and
// settled pills use the same rounded wash, accent link, and strong tokens.
const styles = {
  inlineCode:
    "vui-components-conversationview inlineCode min-w-0 rounded-[var(--vui-radius-chip)] bg-[color-mix(in_srgb,var(--fg-primary)_var(--vui-alpha-wash-faint),transparent)] px-1 py-0.5 font-mono text-vui-xs text-[var(--fg-primary)] whitespace-normal break-words [box-decoration-break:clone]",
  inlineLink:
    "vui-components-conversationview inlineLink min-w-0 text-[var(--accent-cool)] underline decoration-[color-mix(in_srgb,var(--accent-cool)_var(--vui-alpha-line-strong),transparent)] underline-offset-2 hover:decoration-[var(--accent-cool)]",
  inlineStrong:
    "vui-components-conversationview inlineStrong min-w-0 font-semibold text-[var(--fg-primary)]",
} as const;

export default styles;
