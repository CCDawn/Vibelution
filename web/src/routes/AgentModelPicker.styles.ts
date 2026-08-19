import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  contextualHintRow: "flex min-w-0 items-center gap-1.5",
  root: "relative grid min-w-0 gap-1.5",
  trigger: `!flex !min-h-9 !w-full !justify-between !rounded-[10px] !border !border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} !px-2.5 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] [&_[data-slot=vui-button-content]]:!w-full [&_[data-slot=vui-button-content]]:!justify-between`,
  triggerCopy: "flex min-w-0 flex-1 items-center gap-2",
  triggerLabel: "min-w-0 flex-1 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-primary)]",
  triggerMeta: "shrink-0 [font-size:var(--vui-font-xs)] font-normal text-[var(--fg-tertiary)]",
  // Wave 6H dialog policy: prefer 100dvh viewport clamp (not workbench pane-heights).
  dialogContent:
    "w-[min(760px,calc(100vw-48px))] max-h-[calc(100dvh-48px)]",
  dialogBody: "grid min-h-0 min-w-0 gap-3 [grid-template-rows:auto_minmax(0,1fr)]",
  search: "w-full",
  list: "grid min-h-0 min-w-0 gap-2 overflow-y-auto overflow-x-hidden pr-0.5",
  group: "grid min-w-0 gap-1",
  groupHeader: `!sticky !top-0 !z-[1] !flex !min-h-8 !w-full !min-w-0 !items-center !justify-between !gap-2 !rounded-[8px] !border !border-transparent ${vuiFlatPanelClass} !px-2 !py-1 !text-left !shadow-none hover:!border-[var(--vui-border-subtle)] hover:!bg-[var(--vui-control-muted)] [&_[data-slot=vui-button-content]]:!flex [&_[data-slot=vui-button-content]]:!w-full [&_[data-slot=vui-button-content]]:!items-center [&_[data-slot=vui-button-content]]:!justify-between`,
  groupTitle: "flex min-w-0 items-center gap-1.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  groupChevron: "shrink-0 text-[var(--fg-tertiary)]",
  groupCount: "font-normal text-[var(--fg-tertiary)]",
  groupItems: "grid min-w-0 gap-1",
  option: "!grid !h-auto !min-h-[54px] !w-full !min-w-0 !grid-cols-[minmax(0,1fr)_auto] !items-center !gap-3 !rounded-[10px] !border !border-transparent !bg-transparent !px-2.5 !py-2 !text-left !shadow-none hover:!border-[var(--vui-border-subtle)] hover:!bg-[var(--vui-control-muted)] focus-visible:!border-[var(--accent-cool)] [&_[data-slot=vui-button-content]]:contents",
  optionSelected: "!border-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] !bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)]",
  optionDisabled: "opacity-60",
  optionCopy: "grid min-w-0 gap-1",
  optionTitle: "flex min-w-0 flex-wrap items-center gap-1.5 [font-size:var(--vui-font-sm)] font-semibold text-[var(--fg-primary)]",
  optionMeta: "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  action: "shrink-0 text-right [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  badge: "rounded-full border border-[var(--vui-border-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--fg-secondary)]",
  reason: "col-span-2 min-w-0 break-words [font-size:var(--vui-font-xs)] leading-5 text-[var(--status-warning-fg)]",
  check: "shrink-0 text-[var(--accent-cool)]",
  empty: "px-3 py-8 text-center [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  promoteFacts: "grid min-w-0 gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  promoteFact: "min-w-0 break-all",
  promoteFactLabel: "mr-1 font-semibold text-[var(--fg-tertiary)]",
};

export default styles;
