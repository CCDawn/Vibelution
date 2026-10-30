const styles = {
  root:"flex h-full min-h-0 flex-col gap-4 bg-vui-surface-raised px-3 pb-3 pt-5",
  scroll:"min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin]",
  group:"mb-6 flex flex-col gap-1 last:mb-0",
  groupLabel:"m-0 px-3 pb-2 text-vui-micro-10 tracking-wide text-vui-fg-tertiary",
  link:"flex min-h-[38px] w-full items-center gap-3 rounded-lg px-3 text-vui-micro-13 font-normal max-[700px]:min-h-11",
  selectedLink:"border border-vui-border-subtle bg-vui-surface-panel font-semibold text-vui-fg-primary shadow-sm",
  idleLink:"border border-transparent text-vui-fg-secondary hover:bg-vui-surface-row-hover",
  footer:"flex shrink-0 flex-col gap-3",
  returnButton:"!w-full !justify-start !text-vui-micro-13",
  resident:"flex items-center gap-2 border-t border-vui-border-subtle px-2 pt-3 text-vui-micro-10 text-vui-fg-tertiary",
  error:"m-0 break-words px-2 text-vui-xs text-[var(--state-error)]",
  updateBadge:"ml-auto shrink-0 text-vui-micro-10 font-medium text-[var(--accent-primary)]",
} as const;
export default styles;
