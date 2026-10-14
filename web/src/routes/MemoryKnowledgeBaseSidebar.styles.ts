import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  emptyDetail:
    "emptyDetail grid min-h-[96px] min-w-0 content-center gap-2 p-3 text-vui-xs leading-relaxed text-vui-fg-tertiary",
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  governanceMiniPanel:
    "governanceMiniPanel flex min-w-0 flex-wrap items-center gap-2 border-y border-vui-border-subtle px-1 py-2 text-vui-xs [&_strong]:font-medium",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
  panelHeader:
    "panelHeader flex min-w-0 flex-wrap items-center justify-between gap-2 px-1 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  sourceButton:
    "sourceButton min-w-0 !grid w-full grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-2 !min-h-10 !justify-start !border-0 !bg-transparent !px-2 !py-2 !text-left !text-vui-micro-13 hover:!bg-vui-surface-row",
  sourceButtonActive:
    "sourceButtonActive min-w-0 !bg-vui-surface-row !text-vui-fg-primary",
  sourceCopy:
    "sourceCopy grid min-w-0 gap-0.5 text-vui-micro-13 leading-relaxed text-vui-fg-secondary [&_strong]:text-vui-fg-primary [&_strong]:font-medium [&_span]:truncate [&_span]:text-vui-xs",
  sourceIcon:
    "sourceIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  sourceList:
    "sourceList grid min-h-0 min-w-0 content-start gap-1 overflow-auto",
  sourcePanel:
    "sourcePanel grid h-full min-h-0 min-w-0 content-start gap-3 overflow-auto bg-transparent px-2 pb-2 pt-3 text-vui-micro-13",
  sourceStats:
    "sourceStats min-w-0 text-vui-xs tabular-nums text-vui-fg-tertiary",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
