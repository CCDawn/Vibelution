import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const listButton =
  "min-w-0 w-full max-w-full !h-auto text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:gap-1";

const styles = {
  channelPill:
    `channelPill min-w-0 ${vuiControlPillClass}`,
  compactItemMeta:
    "compactItemMeta grid min-w-0 grid-cols-[minmax(0,auto)_minmax(0,1fr)] items-center gap-x-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  compactItemPrimary:
    "compactItemPrimary flex min-w-0 items-baseline justify-between gap-x-2 [font-size:var(--vui-font-xs)] leading-tight [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:font-semibold [&>strong]:text-[var(--fg-primary)] [&>span]:shrink-0 [&>span]:text-[var(--fg-tertiary)]",
  compactItemSummary:
    "compactItemSummary line-clamp-1 min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  // Wave 6F: height from PersistedHeightListShell / pane-heights.v1, not fixed max-h.
  compactMemoryList:
    "compactMemoryList min-w-0 grid min-h-0 content-start gap-1 overflow-auto",
  compactMemoryListFill:
    "compactMemoryListFill h-full min-h-0",
  compactMemoryListResizeHandle:
    "compactMemoryListResizeHandle",
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  itemBadges:
    "itemBadges min-w-0 flex flex-wrap items-center gap-1",
  itemButton: `itemButton ${listButton} ${vuiOpaqueRowClass} px-2 py-1.5`,
  itemButtonActive: `itemButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  itemButtonCompact: "itemButtonCompact min-w-0",
  itemButtonDense: "itemButtonDense min-w-0 min-h-[62px]",
  itemContentButton: `itemContentButton ${listButton} px-0 py-0 shadow-none border-0 bg-transparent`,
  itemContentButtonDense:
    "itemContentButtonDense min-w-0 grid w-full content-start gap-1 [font-size:var(--vui-font-sm)] leading-tight text-[var(--fg-secondary)]",
  itemHeader:
    "itemHeader flex min-w-0 items-baseline justify-between gap-2 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[var(--fg-primary)] [&>span]:shrink-0 [&>span]:text-[var(--fg-tertiary)]",
  itemList:
    "itemList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  itemOrigin:
    "itemOrigin min-w-0 truncate [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  itemPath:
    "itemPath min-w-0 truncate font-mono [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  itemSelectionRow:
    "itemSelectionRow min-w-0 shrink-0",
  itemSelectionRowDense:
    "itemSelectionRowDense min-w-0 pt-0.5",
  itemSummary:
    "itemSummary min-w-0 line-clamp-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  manageItemBadges:
    "manageItemBadges min-w-0 flex flex-wrap items-center gap-1 [&>span]:max-w-full [&>span]:truncate",
  manageItemFooter:
    "manageItemFooter min-w-0 grid gap-1",
  manageItemMeta:
    "manageItemMeta grid min-w-0 grid-cols-[minmax(0,auto)_minmax(0,1fr)] items-center gap-x-2 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  manageItemPrimary:
    "manageItemPrimary flex min-w-0 items-baseline justify-between gap-2 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[var(--fg-primary)] [&>span]:shrink-0 [&>span]:text-[var(--fg-tertiary)]",
  manageItemSummary:
    "manageItemSummary min-w-0 line-clamp-1 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
} as const;

export default styles;
