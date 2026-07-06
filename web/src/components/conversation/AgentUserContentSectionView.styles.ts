const styles = {
  userMessageBody:
    "vui-components-conversationview userMessageBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] w-fit max-w-[min(100%,76ch)] justify-self-end whitespace-pre-wrap rounded-[var(--radius-panel)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-panel))] px-3 py-2 text-left text-[var(--fg-primary)] shadow-[var(--vui-shadow-hairline)] [overflow-wrap:anywhere] [&_.markdownBody]:max-w-[min(100%,76ch)] [&_.markdownBody]:whitespace-normal [&_.markdownBody]:break-words [&_.markdownBody]:[overflow-wrap:anywhere] [&_.inlineLink]:break-words [&_.inlineLink]:[overflow-wrap:anywhere]",
} as const;

export default styles;
