/**
 * Provider-grouped model menu body shared by every host that lets an operator
 * pick a model (Agent slot config and the native Launcher assistant). The
 * shell (popover, width, elevation) stays owned by each host.
 */
const styles = {
  root: "grid min-h-0 min-w-0 gap-3 [grid-template-rows:auto_minmax(0,1fr)]",
  search: "w-full",
  list: "grid max-h-[320px] min-h-0 min-w-0 gap-1 overflow-y-auto overflow-x-hidden",
  group: "grid min-w-0 gap-1",
  groupHeader: "!flex !h-11 !min-h-11 !w-full !min-w-0 !items-center !justify-between !gap-2 !rounded-md !border-transparent ![background:var(--vui-surface-panel)] !px-2 !py-1 !text-left !shadow-none hover:!bg-vui-surface-toolbar [&_[data-slot=vui-button-content]]:!w-full [&_[data-slot=vui-button-content]]:!justify-between",
  groupTitle: "flex min-w-0 items-center gap-1.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  groupChevron: "shrink-0 text-[var(--fg-tertiary)]",
  groupCount: "font-normal text-[var(--fg-tertiary)]",
  groupItems: "grid min-w-0 gap-1",
  option: "!grid !h-auto !min-h-11 !w-full !min-w-0 !grid-cols-[minmax(0,1fr)_auto] !items-center !gap-2 !rounded-md !border-transparent ![background:transparent] !px-3 !py-2 !text-left !text-sm !font-normal !shadow-none hover:![background:var(--vui-surface-toolbar)] [&_[data-slot=vui-button-content]]:contents",
  optionSelected: "![background:var(--vui-surface-toolbar)]",
  optionDisabled: "opacity-60",
  optionCopy: "grid min-w-0 gap-1",
  optionTitle: "flex min-w-0 flex-wrap items-center gap-1.5 text-sm font-normal text-vui-fg-primary",
  optionMeta: "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  action: "shrink-0 text-right [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  reason: "col-span-2 min-w-0 break-words [font-size:var(--vui-font-xs)] leading-5 text-[var(--status-warning-fg)]",
  check: "shrink-0 text-[var(--accent-cool)]",
} as const;

export default styles;
