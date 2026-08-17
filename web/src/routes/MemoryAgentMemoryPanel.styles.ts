import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateCoolInfoClass,
  vuiStateSelectedRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const listButton =
  "min-w-0 w-full max-w-full !h-auto text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:gap-1";

const styles = {
  // Width ownership: VSplitWorkspace + WORKBENCH_LAYOUT_IDS.memory (agent-list / agent-detail).
  agentMemoryWorkspace:
    `agentMemoryWorkspace min-w-0 h-full min-h-0 flex-1 overflow-hidden p-2 ${vuiStateCoolInfoClass}`,
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailHeader:
    "detailHeader min-w-0 grid gap-1 px-1 py-0.5 [&_h2]:min-w-0 [&_h2]:truncate [&_p]:min-w-0 [&_p]:truncate [&_p]:[font-size:var(--vui-font-xs)] [&_p]:text-[var(--fg-tertiary)]",
  detailMeta:
    "detailMeta min-w-0 grid gap-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  detailPanel: `detailPanel min-w-0 h-full min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center justify-items-center gap-1.5 ${vuiFlatPanelClass} p-3 text-center [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  generatedAt:
    "generatedAt min-w-0 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  itemBadges:
    "itemBadges min-w-0 flex flex-wrap items-center gap-1",
  itemButton: `itemButton ${listButton} ${vuiOpaqueRowClass} px-2 py-1.5`,
  itemButtonActive: `itemButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  itemHeader:
    "itemHeader flex min-w-0 items-baseline justify-between gap-2 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[var(--fg-primary)] [&>span]:shrink-0 [&>span]:text-[var(--fg-tertiary)]",
  itemList:
    "itemList min-w-0 grid min-h-0 flex-1 content-start gap-1 overflow-auto",
  itemOrigin:
    "itemOrigin min-w-0 truncate [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  itemPanel: `itemPanel min-w-0 h-full min-h-0 grid grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden ${vuiFlatPanelClass} p-2`,
  itemPath:
    "itemPath min-w-0 truncate font-mono [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  itemSummary:
    "itemSummary min-w-0 line-clamp-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex items-start justify-between gap-1.5 px-1 py-0.5 [&_h2]:min-w-0 [&_h2]:truncate",
  rawPanel: `rawPanel min-w-0 ${vuiFlatPanelClass} p-2 [&_pre]:max-h-[min(28rem,46vh)] [&_pre]:overflow-auto [&_pre]:whitespace-pre-wrap [&_pre]:break-words`,
  searchBox: `searchBox min-w-0 flex items-center gap-1.5 ${vuiOpaqueRowClass} px-2 py-1`,
  sectionPanel: `sectionPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  sourcePanel: `sourcePanel min-w-0 h-full min-h-0 grid grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden ${vuiFlatPanelClass} p-2`,
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillVisible:
    "statusPillVisible min-w-0",
  summaryCard: `summaryCard min-w-0 ${vuiOpaqueRowClass} grid min-h-[54px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:[font-size:var(--vui-font-xs)] [&>strong]:[font-size:var(--vui-font-title)]`,
  summaryGrid: `summaryGrid min-w-0 shrink-0`,
  usageList:
    "usageList min-w-0 grid min-h-0 content-start gap-1 overflow-auto [&>span]:min-w-0 [&>span]:truncate",
  workspace:
    `workspace min-w-0 h-full min-h-0 flex-1 overflow-hidden ${vuiWorkspaceFillClass}`,
} as const;

export default styles;
