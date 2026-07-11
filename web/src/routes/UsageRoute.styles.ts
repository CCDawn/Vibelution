const readablePanelSurface =
  "!bg-[color:color-mix(in_srgb,var(--surface-panel-strong)_98%,var(--surface-page)_2%)] shadow-[0_1px_0_color-mix(in_srgb,var(--surface-page)_70%,transparent)]";
const readableRowSurface =
  "!bg-[color:color-mix(in_srgb,var(--surface-panel-strong)_96%,var(--surface-page)_4%)]";
const panelSurface =
  `rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-vui-surface-panel/88 ${readablePanelSurface}`;
const rowSurface =
  `rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-vui-surface-row/92 ${readableRowSurface}`;
const rowSurfaceHover =
  "hover:border-[var(--vui-border-soft)] hover:bg-[var(--vui-surface-row-hover)]";

const styles = {
  page:
    "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden overflow-x-hidden text-vui-fg-primary max-[860px]:overflow-y-auto max-[860px]:overflow-x-hidden",
  header:
    `mx-2.5 mt-2 min-w-0 max-w-full overflow-hidden border-[var(--vui-border-subtle)] ${readablePanelSurface} max-[720px]:grid-cols-[minmax(0,1fr)] max-[720px]:[&>div:last-child]:w-full max-[720px]:[&>div:last-child]:justify-self-start max-[720px]:[&>div:last-child]:justify-start`,
  headerMeta:
    "min-w-0 max-w-full flex flex-wrap items-center gap-1 max-[720px]:w-full [&_[data-vui=\"status-strip-item\"]]:max-w-full [&_[data-vui=\"status-strip-item\"]]:grid-cols-[auto_minmax(0,1fr)] [&_[data-vui=\"status-strip-item\"]_span]:min-w-0 [&_[data-vui=\"status-strip-item\"]_span]:overflow-hidden [&_[data-vui=\"status-strip-item\"]_span]:text-ellipsis [&_[data-vui=\"status-strip-item\"]_span]:whitespace-nowrap",
  overviewBand:
    "mx-3 mt-2 min-h-[58px] min-w-0 max-w-full overflow-x-auto",
  emptyState:
    "mx-3 mt-2 min-w-0 max-w-full",
  metricBand:
    "grid min-h-0 min-w-0 max-w-full grid-cols-[minmax(0,1fr)_minmax(280px,360px)] gap-1.5 overflow-hidden overflow-x-hidden p-[var(--route-workspace-padding)] max-[980px]:grid-cols-[minmax(0,1fr)] max-[980px]:grid-rows-none max-[860px]:gap-2 max-[860px]:overflow-y-visible max-[860px]:overflow-x-hidden max-[520px]:px-2",
  primaryColumn:
    "grid min-h-0 min-w-0 max-w-full grid-rows-[minmax(0,1fr)_auto] gap-1.5 overflow-hidden max-[980px]:grid-rows-none max-[980px]:overflow-y-visible max-[980px]:overflow-x-hidden",
  compositionPanel:
    `grid min-h-0 min-w-0 max-w-full grid-rows-[auto_auto_minmax(0,1fr)] gap-1.5 overflow-hidden ${panelSurface} p-2`,
  rollupPanel:
    `grid min-h-0 min-w-0 max-w-full gap-1.5 overflow-hidden ${panelSurface} p-2`,
  recordPanel:
    `grid min-h-0 min-w-0 max-w-full grid-rows-[auto_auto_minmax(0,1fr)] gap-1.5 overflow-hidden ${panelSurface} p-2 max-[980px]:overflow-y-visible max-[980px]:overflow-x-hidden`,
  panelHeader:
    "flex min-w-0 max-w-full flex-wrap items-center justify-between gap-1.5 [&>div]:min-w-0 [&_h2]:m-0 [&_h2]:min-w-0 [&_h2]:overflow-hidden [&_h2]:text-ellipsis [&_h2]:whitespace-nowrap [&_h2]:text-[0.9rem] [&_h2]:leading-tight [&_h2]:text-vui-fg-primary",
  panelEyebrow:
    "m-0 mb-0.5 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[var(--vui-font-xs)] uppercase tracking-[0.06em] text-vui-fg-tertiary",
  countPill:
    "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 overflow-hidden text-ellipsis whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] px-2 text-[var(--vui-font-xs)] text-[var(--accent-cool)] [&_svg]:flex-none",
  sourceGrid:
    "grid min-w-0 max-w-full grid-cols-[repeat(2,minmax(0,1fr))] gap-1 max-[520px]:grid-cols-1",
  sourceTile:
    `grid min-h-[50px] min-w-0 max-w-full gap-0.5 ${rowSurface} px-2 py-1.5 [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.9rem] [&_strong]:leading-tight [&_strong]:text-vui-fg-primary`,
  sourceTileObserved:
    "border-[color-mix(in_srgb,var(--state-success)_30%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_8%,var(--vui-surface-row))]",
  sourceTileEstimated:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))]",
  sourceTileMissing:
    "border-[color-mix(in_srgb,var(--state-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_9%,var(--vui-surface-row))]",
  sourceTileEmpty:
    "border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_88%,transparent)]",
  usageList:
    "grid min-h-0 min-w-0 max-w-full content-start gap-1 overflow-auto overflow-x-hidden pr-1",
  rollupGrid:
    "grid min-w-0 max-w-full grid-cols-[repeat(2,minmax(0,1fr))] gap-1 max-[720px]:grid-cols-1",
  usageRow:
    `grid min-w-0 max-w-full grid-cols-[minmax(96px,0.64fr)_minmax(0,1fr)_minmax(58px,max-content)_minmax(54px,max-content)] items-center gap-1.5 ${rowSurface} ${rowSurfaceHover} px-2 py-1.5 max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:items-start [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_code]:inline-flex [&_code]:min-w-0 [&_code]:max-w-full [&_code]:items-center [&_code]:gap-1 [&_code]:overflow-hidden [&_code]:text-ellipsis [&_code]:whitespace-nowrap [&_code]:font-mono [&_code]:text-[var(--vui-font-xs)] [&_code]:text-[var(--accent-cool)]`,
  usageRowWide:
    "grid grid-cols-[minmax(104px,0.68fr)_minmax(0,1.1fr)_minmax(72px,max-content)] max-[620px]:grid-cols-[minmax(0,1fr)]",
  refreshButton:
    "h-[var(--vui-control-height-sm)] min-h-8 w-[var(--vui-control-height-sm)] flex-none p-0",
  progressTrack:
    "h-1.5 min-w-0 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_48%,transparent)]",
  progressFill:
    "block h-full rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_58%,var(--state-success)_22%)]",
  quietState:
    `m-0 min-w-0 max-w-full ${rowSurface} px-2 py-1.5 text-[var(--vui-font-xs)] leading-tight text-vui-fg-tertiary [overflow-wrap:anywhere]`,
  detailGrid:
    "grid min-h-0 min-w-0 max-w-full content-start gap-1 overflow-auto overflow-x-hidden pr-1",
  detailRow:
    `grid min-w-0 max-w-full grid-cols-[minmax(96px,0.5fr)_minmax(0,1fr)] gap-1.5 ${rowSurface} px-2 py-1.5 max-[520px]:grid-cols-[minmax(0,1fr)] [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  breakdownList:
    "grid min-h-0 min-w-0 max-w-full content-start gap-1 overflow-auto overflow-x-hidden pr-1",
  breakdownRow:
    `grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5 ${rowSurface} px-2 py-1.5 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary`,
} as const;

export default styles;
