const styles = {
  // surface-role: answer-body — prose, not a bubble. Long-answer collapse
  // reuses the user-bubble mechanics (ZCode-aligned): the clamp lives on a
  // wrapper while the measured child keeps natural height, so ResizeObserver
  // still sees real content growth (async images included).
  assistantBody: "vui-components-conversationview assistantMessageBody min-w-0",
  assistantBodyWrap:
    "vui-components-conversationview assistantMessageBodyWrap relative min-w-0",
  assistantBodyClamped:
    "vui-components-conversationview assistantMessageBodyClamped relative min-w-0 max-h-[480px] overflow-hidden",
  // The fade uses the chat surface token, not the rail tint: an answer sits
  // directly on the transcript background, with no bubble surface behind it.
  assistantCollapseFade:
    "vui-components-conversationview assistantMessageCollapseFade pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-[var(--vui-surface-chat)] to-transparent",
  assistantCollapseToggle:
    "vui-components-conversationview assistantMessageCollapseToggle mt-2 flex cursor-pointer items-center gap-1 border-0 border-t border-solid border-[var(--vui-border-subtle)] bg-transparent p-0 pt-2 text-left [font-size:var(--vui-type-caption-size)] text-[var(--fg-tertiary)] hover:text-[var(--fg-secondary)]",
  assistantCollapseChevron:
    "shrink-0 transition-transform duration-150 data-[assistant-content-collapse-chevron=collapsed]:rotate-0 data-[assistant-content-collapse-chevron=expanded]:rotate-180",
} as const;

export default styles;
