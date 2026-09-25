const styles = {
  // surface-role: message-bubble — neutral Codex-style authored content
  //
  // Long-message collapse (ZCode-aligned): the clamp lives on a wrapper while
  // the measured child keeps natural height, so ResizeObserver still sees real
  // content growth (async images included). The fade reuses the bubble's own
  // token surface so it reads as the message running past the fold.
  userMessageBodyWrap: "vui-components-conversationview userMessageBodyWrap relative min-w-0",
  userMessageBodyClamped:
    "vui-components-conversationview userMessageBodyClamped relative min-w-0 max-h-[120px] overflow-hidden",
  userMessageCollapseFade:
    "vui-components-conversationview userMessageCollapseFade pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-[var(--vui-control-muted)] to-transparent",
  userMessageCollapseToggle:
    "vui-components-conversationview userMessageCollapseToggle mt-1 flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-left [font-size:var(--vui-type-caption-size)] text-[var(--fg-tertiary)] hover:text-[var(--fg-secondary)]",
  userMessageBody:
    "vui-components-conversationview userMessageBody min-w-0 w-fit max-w-full justify-self-end whitespace-pre-wrap rounded-[16px] border-0 bg-[var(--vui-control-muted)] px-3 py-2 text-left text-vui-sm leading-[var(--vui-line-readable)] text-[var(--fg-primary)] shadow-none [overflow-wrap:anywhere] [&_.markdownBody]:max-w-full [&_.markdownBody]:whitespace-normal [&_.markdownBody]:break-words [&_.markdownBody]:[overflow-wrap:anywhere] [&_.inlineLink]:break-words [&_.inlineLink]:[overflow-wrap:anywhere]",
} as const;

export default styles;
