const styles = {
  // surface-role: message-bubble — neutral Codex-style authored content
  userMessageBody:
    "vui-components-conversationview userMessageBody min-w-0 w-fit max-w-full justify-self-end whitespace-pre-wrap rounded-[16px] border-0 bg-[var(--vui-control-muted)] px-3 py-2 text-left [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-primary)] shadow-none [overflow-wrap:anywhere] [&_.markdownBody]:max-w-full [&_.markdownBody]:whitespace-normal [&_.markdownBody]:break-words [&_.markdownBody]:[overflow-wrap:anywhere] [&_.inlineLink]:break-words [&_.inlineLink]:[overflow-wrap:anywhere]",
} as const;

export default styles;
