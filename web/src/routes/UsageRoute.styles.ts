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
    "grid h-full min-h-0 min-w-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden text-vui-fg-primary max-[860px]:overflow-auto",
  header:
    `mx-2.5 mt-2 min-w-0 border-[var(--vui-border-subtle)] ${readablePanelSurface}`,
  headerMeta:
    "min-w-0 flex flex-wrap items-center gap-1.5",
  overviewBand:
    `grid min-w-0 grid-cols-[minmax(240px,0.7fr)_minmax(0,1.3fr)] gap-2 px-3 pt-2 max-[820px]:grid-cols-1`,
  heroMetric:
    `grid min-w-0 gap-1.5 ${panelSurface} px-3 py-2.5 text-left [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[1.42rem] [&_strong]:leading-none [&_strong]:text-vui-fg-primary [&_small]:min-w-0 [&_small]:overflow-hidden [&_small]:text-ellipsis [&_small]:whitespace-nowrap [&_small]:text-[var(--vui-font-xs)] [&_small]:text-vui-fg-secondary`,
  overviewStats:
    "grid min-w-0 grid-cols-[repeat(3,minmax(0,1fr))] gap-2 max-[640px]:grid-cols-1",
  overviewStat:
    `grid min-w-0 gap-1 ${panelSurface} px-2.5 py-2 text-left [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[1.02rem] [&_strong]:leading-tight [&_strong]:text-vui-fg-primary [&_small]:min-w-0 [&_small]:overflow-hidden [&_small]:text-ellipsis [&_small]:whitespace-nowrap [&_small]:text-[var(--vui-font-xs)] [&_small]:text-vui-fg-secondary`,
  metricBand:
    "grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)_minmax(300px,380px)] gap-2 p-[var(--route-workspace-padding)] max-[980px]:grid-cols-[minmax(0,1fr)] max-[980px]:grid-rows-none max-[860px]:gap-3.5",
  primaryColumn:
    "grid min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] gap-2 max-[980px]:grid-rows-none",
  compositionPanel:
    `grid min-h-0 min-w-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-2.5 ${panelSurface} p-2.5`,
  rollupPanel:
    `grid min-h-0 min-w-0 gap-2.5 ${panelSurface} p-2.5`,
  recordPanel:
    `grid min-h-0 min-w-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-2.5 ${panelSurface} p-2.5`,
  panelHeader:
    "flex min-w-0 flex-wrap items-center justify-between gap-2 [&_h2]:m-0 [&_h2]:text-[0.94rem] [&_h2]:leading-tight [&_h2]:text-vui-fg-primary",
  panelEyebrow:
    "m-0 mb-0.5 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  countPill:
    "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] px-2 text-[var(--vui-font-xs)] text-[var(--accent-cool)]",
  sourceGrid:
    "grid min-w-0 grid-cols-[repeat(2,minmax(0,1fr))] gap-1.5 max-[520px]:grid-cols-1",
  sourceTile:
    `grid min-w-0 gap-1 ${rowSurface} px-2 py-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:text-[0.95rem] [&_strong]:leading-tight [&_strong]:text-vui-fg-primary`,
  sourceTileObserved:
    "border-[color-mix(in_srgb,var(--state-success)_30%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_8%,var(--vui-surface-row))]",
  sourceTileEstimated:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))]",
  sourceTileMissing:
    "border-[color-mix(in_srgb,var(--state-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_9%,var(--vui-surface-row))]",
  sourceTileEmpty:
    "border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_88%,transparent)]",
  usageList:
    "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  rollupGrid:
    "grid min-w-0 grid-cols-[repeat(2,minmax(0,1fr))] gap-1.5 max-[720px]:grid-cols-1",
  usageRow:
    `grid min-w-0 grid-cols-[minmax(110px,0.72fr)_minmax(0,1fr)_auto_auto] items-center gap-2 ${rowSurface} ${rowSurfaceHover} px-2.5 py-2 max-[620px]:grid-cols-[minmax(0,1fr)] [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-sm)] [&_strong]:text-vui-fg-primary [&_code]:inline-flex [&_code]:min-w-0 [&_code]:items-center [&_code]:gap-1 [&_code]:font-mono [&_code]:text-[var(--vui-font-xs)] [&_code]:text-[var(--accent-cool)]`,
  usageRowWide:
    "grid-cols-[minmax(120px,0.72fr)_minmax(0,1.1fr)_minmax(90px,auto)]",
  progressTrack:
    "h-1.5 min-w-0 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_48%,transparent)]",
  progressFill:
    "block h-full rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_58%,var(--state-success)_22%)]",
  quietState:
    `m-0 ${rowSurface} px-2.5 py-2 text-[var(--vui-font-xs)] leading-tight text-vui-fg-tertiary`,
  errorState:
    "mx-3 mt-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] px-2.5 py-2 text-[var(--vui-font-xs)] text-[var(--state-error)]",
  detailGrid:
    "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  detailRow:
    `grid min-w-0 grid-cols-[minmax(105px,0.58fr)_minmax(0,1fr)] gap-2 ${rowSurface} px-2 py-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  breakdownList:
    "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  breakdownRow:
    `grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 ${rowSurface} px-2 py-1.5 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary`,
} as const;

export default styles;
