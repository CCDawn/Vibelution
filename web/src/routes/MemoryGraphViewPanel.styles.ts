const styles = {
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  graphCanvasFallback:
    "graphCanvasFallback min-w-0 grid min-h-0 gap-2 p-2",
  graphCanvasPanel:
    "graphCanvasPanel min-w-0 grid h-full min-h-0 gap-2 p-2 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)]",
  graphCanvasToolbar:
    "graphCanvasToolbar min-w-0 grid min-h-0 gap-2 p-2 flex flex-wrap items-center gap-1.5",
  graphClearFocusButton:
    "graphClearFocusButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  graphInteractionHint:
    "graphInteractionHint min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  graphNodeList:
    "graphNodeList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  graphNodeTypeMark:
    "graphNodeTypeMark min-w-0",
  graphTypeList:
    "graphTypeList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [&_button]:w-full [&_[data-active=true]]:border-[var(--accent-cool)]",
  graphWorkspace:
    "graphWorkspace min-w-0 grid h-full min-h-0 gap-2 p-2 grid-cols-[minmax(210px,250px)_minmax(760px,1fr)_minmax(260px,0.34fr)] overflow-hidden max-[1280px]:grid-cols-[minmax(200px,240px)_minmax(560px,1fr)_minmax(240px,0.42fr)] max-[980px]:grid-cols-1 max-[980px]:overflow-auto",
  itemButton:
    "itemButton min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  itemButtonActive:
    "itemButtonActive min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel:
    "managementPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  panelEyebrow:
    "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  searchBox:
    "searchBox min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  sourcePanel:
    "sourcePanel min-w-0 min-h-0 overflow-auto rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  summaryCard:
    "summaryCard min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 grid min-h-[54px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:text-[var(--vui-font-xs)] [&>strong]:text-[var(--vui-font-title)]",
  summaryGrid:
    "summaryGrid min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 grid gap-2 grid-cols-[repeat(6,minmax(118px,1fr))] gap-1.5 max-[1180px]:grid-cols-3 max-[720px]:grid-cols-2",
  workspace:
    "workspace min-w-0 grid h-full min-h-0 flex-1 gap-2 p-2 grid-rows-[minmax(0,1fr)] overflow-auto",
} as const;

export default styles;
