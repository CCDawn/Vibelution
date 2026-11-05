const styles = {
  root:"flex h-full min-h-0 flex-col bg-vui-surface-rail",
  features:"flex shrink-0 flex-col gap-1 border-b border-vui-border-subtle px-3 pb-4 pt-5",
  tasks:"min-h-0 flex-1 overflow-hidden px-3 pt-3",
  groupLabel:"m-0 px-3 pb-2 text-vui-micro-10 tracking-wide text-vui-fg-tertiary",
  link:"flex min-h-[38px] w-full items-center gap-3 rounded-lg px-3 text-vui-micro-13 font-normal max-[700px]:min-h-11",
  selectedLink:"border border-vui-border-subtle bg-vui-surface-panel font-semibold text-vui-fg-primary shadow-sm",
  idleLink:"border border-transparent text-vui-fg-secondary hover:bg-vui-surface-row-hover",
  footer:"flex shrink-0 flex-col gap-2 border-t border-vui-border-subtle px-3 py-3",
  returnButton:"!w-full !justify-start !text-vui-micro-13",
  error:"m-0 break-words px-2 text-vui-xs text-[var(--state-error)]",
  updateLink:"[&>[data-slot=vui-button-content]]:w-full [&>[data-slot=vui-button-content]]:justify-start [&_[data-slot=vui-button-trailing-icon]]:ml-auto",
  updateBadge:"shrink-0 text-vui-micro-11 font-medium text-[var(--accent-primary)]",
} as const;
export default styles;
