import { agentConfigControlClass } from "./agentConfigForm.styles";

const styles = {
  contextualHintRow: "flex min-w-0 items-center gap-1.5",
  root: "relative grid min-w-0 gap-1.5",
  trigger: `${agentConfigControlClass} !flex !w-full !justify-between !gap-3 !text-left !font-normal [&_[data-slot=vui-button-content]]:!w-full [&_[data-slot=vui-button-content]]:!justify-between`,
  triggerCopy: "flex min-w-0 flex-1 items-center gap-2",
  triggerLabel: "min-w-0 flex-1 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-primary)]",
  triggerMeta: "shrink-0 [font-size:var(--vui-font-xs)] font-normal text-[var(--fg-tertiary)]",
  // Wave 6H dialog policy: prefer 100dvh viewport clamp (not workbench pane-heights).
  dialogContent:
    "!w-[352px] !max-w-[calc(100vw-32px)] !max-h-[calc(100dvh-32px)] !rounded-lg !border-vui-border-subtle !bg-vui-surface-panel !p-2 !shadow-lg",
  dialogBody: "grid min-h-0 min-w-0 gap-3 [grid-template-rows:auto_minmax(0,1fr)]",
  search: `${agentConfigControlClass} w-full`,
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
  badge: "rounded-full border border-[var(--vui-border-subtle)] px-1.5 py-0.5 text-vui-micro-10 font-medium text-[var(--fg-secondary)]",
  reason: "col-span-2 min-w-0 break-words [font-size:var(--vui-font-xs)] leading-5 text-[var(--status-warning-fg)]",
  check: "shrink-0 text-[var(--accent-cool)]",
  empty: "px-3 py-8 text-center [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  promoteFacts: "grid min-w-0 gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  promoteFact: "min-w-0 break-all",
  promoteFactLabel: "mr-1 font-semibold text-[var(--fg-tertiary)]",
};

export default styles;
