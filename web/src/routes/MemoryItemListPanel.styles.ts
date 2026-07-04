const styles = {
  channelPill:
    "channelPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  compactItemMeta:
    "compactItemMeta flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  compactItemPrimary:
    "compactItemPrimary flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 text-[var(--vui-font-xs)] leading-tight [&>strong]:min-w-0 [&>strong]:font-semibold [&>strong]:text-[var(--fg-primary)] [&>span]:shrink-0 [&>span]:text-[var(--fg-tertiary)]",
  compactItemSummary:
    "compactItemSummary line-clamp-2 min-w-0 text-[var(--vui-font-xs)] leading-[1.35] text-[var(--fg-secondary)]",
  compactMemoryList:
    "compactMemoryList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto max-h-[148px]",
  emptyState:
    "emptyState min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  itemBadges:
    "itemBadges min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemButton:
    "itemButton min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  itemButtonActive:
    "itemButtonActive min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  itemButtonCompact:
    "itemButtonCompact min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemButtonDense:
    "itemButtonDense min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 min-h-[62px]",
  itemContentButton:
    "itemContentButton min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)]",
  itemContentButtonDense:
    "itemContentButtonDense min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] grid grid-rows-[16px_14px_18px]",
  itemHeader:
    "itemHeader min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemList:
    "itemList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemOrigin:
    "itemOrigin min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemPath:
    "itemPath min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 font-mono text-[var(--vui-font-xs)]",
  itemSelectionRow:
    "itemSelectionRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemSelectionRowDense:
    "itemSelectionRowDense min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  itemSummary:
    "itemSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 rounded-[var(--radius-control)] bg-[var(--vui-surface-row)]",
  manageItemBadges:
    "manageItemBadges min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 grid grid-cols-[repeat(auto-fit,minmax(82px,1fr))] max-h-[74px] [&>span]:truncate",
  manageItemFooter:
    "manageItemFooter min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  manageItemMeta:
    "manageItemMeta min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  manageItemPrimary:
    "manageItemPrimary min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  manageItemSummary:
    "manageItemSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 rounded-[var(--radius-control)] bg-[var(--vui-surface-row)]",
  statusPill:
    "statusPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
