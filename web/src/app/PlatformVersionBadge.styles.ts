// Compact top-bar version strip: one small trigger plus one small popover.
// Classes live here so product source never grows inline visual utilities.
export const platformVersionBadgeStyles = {
  trigger:
    "vui-app-appshell platformVersionTrigger flex min-w-0 items-center gap-1 whitespace-nowrap rounded-[var(--radius-control)] px-1.5 py-0.5 text-[var(--vui-font-xs)] font-medium text-[var(--fg-tertiary)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--fg-secondary)]",
  panel: "w-[248px] p-3",
  head: "flex items-baseline justify-between gap-2",
  version: "text-[15px] font-semibold text-[var(--fg-primary)]",
  build: "text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  progressRow:
    "mt-2 flex items-center justify-between gap-2 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  bar: "mt-1 h-1 w-full overflow-hidden rounded-full bg-[var(--vui-border-subtle)]",
  barFill: "h-full rounded-full bg-[var(--accent-cool)]",
  pending:
    "mt-2 rounded-[var(--radius-control)] bg-[var(--vui-surface-row-hover)] px-2 py-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)]",
  list: "mt-2 flex flex-col gap-1",
  item: "flex items-baseline justify-between gap-2 text-[var(--vui-font-xs)]",
  itemVersion: "font-medium text-[var(--fg-primary)]",
  itemMeta: "text-[var(--fg-tertiary)]",
  empty: "mt-2 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
} as const;
