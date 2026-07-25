import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  channelPill:
    `channelPill min-w-0 ${vuiControlPillClass}`,
  compactItemMeta:
    "compactItemMeta flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  compactItemPrimary:
    "compactItemPrimary flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 [font-size:var(--vui-font-xs)] leading-tight [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:font-semibold [&>strong]:text-[var(--fg-primary)] [&>span]:shrink-0 [&>span]:text-[var(--fg-tertiary)]",
  compactItemSummary:
    "compactItemSummary line-clamp-2 min-w-0 [font-size:var(--vui-font-xs)] leading-[1.35] text-[var(--fg-secondary)]",
  // Wave 6F: height from PersistedHeightListShell / pane-heights.v1, not fixed max-h.
  compactMemoryList:
    "compactMemoryList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  compactMemoryListResizeHandle:
    "compactMemoryListResizeHandle",
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  itemBadges: `itemBadges min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemButton: `itemButton !h-auto min-w-0 w-full max-w-full ${vuiOpaqueRowClass} p-2 text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:gap-1.5`,
  itemButtonActive: `itemButtonActive min-w-0 ${vuiOpaqueRowClass} p-2 ${vuiStateSelectedRowClass}`,
  itemButtonCompact: `itemButtonCompact min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemButtonDense: `itemButtonDense min-w-0 ${vuiOpaqueRowClass} p-2 min-h-[62px]`,
  itemContentButton: `itemContentButton min-w-0 w-full max-w-full ${vuiOpaqueRowClass} p-2 text-left [font-size:var(--vui-font-sm)] font-semibold leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:gap-1.5`,
  itemContentButtonDense: `itemContentButtonDense min-w-0 ${vuiOpaqueRowClass} p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] grid grid-rows-[16px_14px_18px]`,
  itemHeader: `itemHeader min-w-0 flex flex-wrap items-center gap-1.5 ${vuiOpaqueRowClass} p-2`,
  itemList: `itemList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${vuiOpaqueRowClass} p-2`,
  itemOrigin: `itemOrigin min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemPath: `itemPath min-w-0 ${vuiOpaqueRowClass} p-2 font-mono [font-size:var(--vui-font-xs)] break-all`,
  itemSelectionRow: `itemSelectionRow min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemSelectionRowDense: `itemSelectionRowDense min-w-0 ${vuiOpaqueRowClass} p-2`,
  itemSummary: `itemSummary min-w-0 line-clamp-3 ${vuiOpaqueRowClass} p-2`,
  manageItemBadges: `manageItemBadges min-w-0 ${vuiOpaqueRowClass} p-2 grid grid-cols-[repeat(auto-fit,minmax(82px,1fr))] max-h-[74px] [&>span]:truncate`,
  manageItemFooter: `manageItemFooter min-w-0 flex flex-wrap items-center gap-1.5 ${vuiOpaqueRowClass} p-2`,
  manageItemMeta: `manageItemMeta min-w-0 flex flex-wrap items-center gap-1.5 ${vuiOpaqueRowClass} p-2`,
  manageItemPrimary: `manageItemPrimary min-w-0 ${vuiOpaqueRowClass} p-2 ${vuiStateSelectedRowClass}`,
  manageItemSummary: `manageItemSummary min-w-0 line-clamp-2 ${vuiOpaqueRowClass} p-2`,
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
} as const;

export default styles;
