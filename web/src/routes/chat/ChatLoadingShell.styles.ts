const styles = {
  pulse:
    "animate-pulse bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)]",
  indexShell:
    "grid min-w-0 content-start gap-0.5 px-1 py-0.5",
  indexCard:
    "grid min-h-[44px] grid-cols-[32px_minmax(0,1fr)] items-center gap-2 rounded-[var(--radius-control)] px-2 py-1.5",
  indexAvatar:
    "size-8 rounded-full",
  indexCopy:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  indexTitle:
    "h-3 w-16 rounded-full",
  indexMeta:
    "h-2.5 w-8 rounded-full",
  workspaceShell:
    "relative grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden",
  transcript:
    "grid min-h-0 content-start gap-7 overflow-hidden px-[clamp(18px,7vw,112px)] pb-6 pt-8",
  assistantTurn:
    "grid w-full max-w-[760px] grid-cols-[2rem_minmax(0,1fr)] items-start gap-x-3",
  userTurn:
    "ml-auto grid w-[min(420px,68%)] justify-items-end gap-2",
  avatar:
    "size-8 rounded-full",
  messageCopy:
    "grid min-w-0 gap-2.5 pt-1",
  messageHeading:
    "h-2.5 w-28 rounded-full",
  messageLineWide:
    "h-2.5 w-full rounded-full",
  messageLine:
    "h-2.5 w-[78%] rounded-full opacity-80",
  userBubble:
    "h-10 w-full rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_74%,transparent)] !bg-[var(--vui-surface-row)]",
  composerWrap:
    "mx-auto mb-[18px] box-border grid w-[min(calc(100%_-_36px),760px)] min-h-[104px] gap-1.5 rounded-[16px] border border-[color-mix(in_srgb,var(--fg-primary)_13%,transparent)] bg-[var(--vui-surface-panel)] px-3.5 py-2.5 max-[719px]:mb-[10px] max-[719px]:min-h-[96px] max-[719px]:rounded-[14px]",
  composerInput:
    "min-h-[48px] w-[42%] rounded-full",
  composerToolbar:
    "flex min-h-8 items-center justify-between gap-2 pt-1.5",
  composerTool:
    "h-6 w-16 rounded-full",
  composerSend:
    "h-8 w-16 rounded-[var(--radius-control)]",
} as const;

export default styles;
