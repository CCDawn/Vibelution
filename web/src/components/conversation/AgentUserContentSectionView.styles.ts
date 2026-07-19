const styles = {
  userMessageBody:
    "vui-components-conversationview userMessageBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] w-fit max-w-[min(100%,68ch)] justify-self-end whitespace-pre-wrap rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-surface-panel))] px-2.5 py-1.5 text-left text-[var(--fg-primary)] shadow-none [overflow-wrap:anywhere] [&_.markdownBody]:max-w-[min(100%,68ch)] [&_.markdownBody]:whitespace-normal [&_.markdownBody]:break-words [&_.markdownBody]:[overflow-wrap:anywhere] [&_.inlineLink]:break-words [&_.inlineLink]:[overflow-wrap:anywhere]",
} as const;

export default styles;
