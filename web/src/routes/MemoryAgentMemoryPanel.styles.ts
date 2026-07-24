import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  agentMemoryWorkspace:
    "agentMemoryWorkspace min-w-0 grid h-full min-h-0 gap-2 p-2 grid-cols-[minmax(210px,260px)_minmax(0,1fr)_minmax(280px,0.42fr)] overflow-hidden border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] max-[1100px]:grid-cols-[minmax(220px,280px)_minmax(0,1fr)] max-[1100px]:[&_.detailPanel]:col-span-2 max-[780px]:grid-cols-1 max-[780px]:overflow-auto",
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  detailHeader:
    "detailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  detailMeta:
    "detailMeta min-w-0 flex flex-wrap items-center gap-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  detailPanel: `detailPanel min-w-0 min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  generatedAt:
    "generatedAt min-w-0",
  itemBadges: `itemBadges min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemButton: `itemButton !h-auto min-w-0 ${vuiOpaqueRowClass} p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55`,
  itemButtonActive: `itemButtonActive min-w-0 ${vuiOpaqueRowClass} p-2 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]`,
  itemHeader: `itemHeader min-w-0 flex flex-wrap items-center gap-1.5 ${vuiOpaqueRowClass} p-2`,
  itemList: `itemList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${vuiOpaqueRowClass} p-2`,
  itemOrigin: `itemOrigin min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemPanel: `itemPanel min-w-0 min-h-0 overflow-auto ${vuiOpaqueRowClass} p-2`,
  itemPath: `itemPath min-w-0 ${vuiOpaqueRowClass} p-2 font-mono [font-size:var(--vui-font-xs)]`,
  itemSummary: `itemSummary min-w-0 ${vuiOpaqueRowClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  rawPanel: `rawPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  searchBox: `searchBox min-w-0 ${vuiFlatPanelClass} p-2`,
  sectionPanel: `sectionPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  sourcePanel: `sourcePanel min-w-0 min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  statusPill:
    "statusPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  statusPillVisible:
    "statusPillVisible min-w-0",
  summaryCard: `summaryCard min-w-0 ${vuiOpaqueRowClass} grid min-h-[54px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:[font-size:var(--vui-font-xs)] [&>strong]:[font-size:var(--vui-font-title)]`,
  summaryGrid: `summaryGrid min-w-0 ${vuiFlatPanelClass} p-2 grid gap-2 grid-cols-[repeat(6,minmax(118px,1fr))] gap-1.5 max-[1180px]:grid-cols-3 max-[720px]:grid-cols-2`,
  usageList:
    "usageList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workspace:
    "workspace min-w-0 grid h-full min-h-0 flex-1 gap-2 p-2 grid-rows-[minmax(0,1fr)] overflow-auto",
} as const;

export default styles;
