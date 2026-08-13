const styles = {
  root:
    "grid h-full min-h-[320px] min-w-0 w-full content-start overflow-hidden bg-transparent",
  transcript:
    "mx-auto grid w-full max-w-[880px] content-start gap-9 px-[clamp(24px,5vw,64px)] py-[clamp(36px,7vh,76px)]",
  assistantTurn:
    "grid min-w-0 max-w-[720px] grid-cols-[28px_minmax(0,1fr)] items-start gap-3",
  avatar: "size-7 opacity-70",
  message: "grid min-w-0 gap-2.5 pt-0.5",
  messageHeadingWide: "w-24 opacity-75",
  messageHeadingCompact: "w-20 opacity-75",
  messageLineWide: "w-[86%]",
  messageLineMedium: "w-[78%]",
  messageLineCompact: "w-[64%] opacity-75",
  messageLineShort: "w-[52%] opacity-75",
  userTurn:
    "ml-auto grid w-[min(420px,62%)] min-w-[220px] justify-items-end gap-2",
  userBubble:
    "h-11 w-full rounded-[14px] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] opacity-75",
  visuallyHidden: "sr-only",
} as const;

export default styles;
