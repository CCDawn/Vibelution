import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  governanceMiniPanel: `governanceMiniPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  sourceButton:
    `sourceButton min-w-0 ${vuiControlQuietClass} !grid grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-2 min-h-10 px-[7px] py-[5px]`,
  sourceButtonActive:
    `sourceButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  sourceCopy:
    "sourceCopy min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  sourceIcon:
    "sourceIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  sourceList:
    "sourceList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  sourcePanel: `sourcePanel min-w-0 min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  sourceStats:
    "sourceStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
