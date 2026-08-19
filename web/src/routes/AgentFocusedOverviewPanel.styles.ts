const styles = {
  overview:
    "grid min-h-full min-w-0 content-start gap-3 [grid-template-rows:auto_minmax(0,_1fr)]",
  metricStrip:
    "w-full [&_[data-vui=metric-strip]]:w-full [&>div]:min-w-[150px] [&>div]:flex-1 max-[680px]:[&>div]:min-w-[calc(50%-1px)] max-[440px]:[&>div]:min-w-full",
  workspace:
    "grid min-h-[520px] min-w-0 grid-cols-[minmax(0,_1.6fr)_minmax(280px,_0.85fr)] items-stretch gap-3 max-[1180px]:min-h-0 max-[1180px]:grid-cols-1",
  mainColumn: "grid min-w-0 content-start gap-3",
  sideColumn:
    "grid min-w-0 content-start gap-3 [grid-template-rows:auto_auto_minmax(0,_1fr)]",
  surface: "grid min-w-0 content-start gap-2 overflow-hidden",
  sectionHeader:
    "flex min-w-0 flex-wrap items-start justify-between gap-2 border-b border-[var(--vui-border-hairline)] pb-2",
  sectionTitle: "grid min-w-0 gap-0.5",
  eyebrow:
    "m-0 [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-[0.07em] text-[var(--fg-tertiary)]",
  heading:
    "m-0 min-w-0 [overflow-wrap:anywhere] text-[var(--fg-primary)] [font-size:var(--vui-font-md)] font-bold",
  sectionCount:
    "inline-flex min-h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-[var(--vui-control-muted)] px-1.5 [font-size:var(--vui-font-xs)] font-bold text-[var(--fg-secondary)]",
  effectiveTable: "grid min-w-0 gap-1",
  effectiveHeader:
    "grid min-w-0 grid-cols-[minmax(120px,_0.9fr)_minmax(150px,_1.4fr)_minmax(96px,_0.75fr)_auto] gap-2 px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)] max-[760px]:hidden",
  effectiveRow:
    "grid min-w-0 grid-cols-[minmax(120px,_0.9fr)_minmax(150px,_1.4fr)_minmax(96px,_0.75fr)_auto] items-center gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-hairline)] bg-[var(--vui-surface-row)] px-2 py-2 max-[760px]:grid-cols-[minmax(0,_1fr)_auto] max-[760px]:items-start",
  effectiveIdentity:
    "grid min-w-0 gap-0.5 [&>strong]:min-w-0 [&>strong]:[overflow-wrap:anywhere] [&>strong]:[font-size:var(--vui-font-sm)]",
  effectiveSource:
    "min-w-0 truncate [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)] max-[760px]:col-start-1 max-[760px]:row-start-2",
  effectiveValue:
    "min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-sm)] font-semibold text-[var(--fg-secondary)] max-[760px]:col-span-2 max-[760px]:row-start-3",
  effectiveStatus:
    "min-w-0 justify-self-end max-[760px]:col-start-2 max-[760px]:row-span-2 max-[760px]:row-start-1",
  activityList: "grid min-w-0 gap-1",
  activityItem:
    "grid min-w-0 grid-cols-[minmax(0,_1fr)_auto] gap-x-3 gap-y-1 rounded-[var(--radius-control)] border border-[var(--vui-border-hairline)] bg-[var(--vui-surface-row)] px-2 py-2 max-[560px]:grid-cols-1",
  activityTitle:
    "m-0 min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-sm)] font-bold text-[var(--fg-primary)]",
  activityBody:
    "col-start-1 m-0 min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)]",
  activityMeta:
    "col-start-2 row-start-1 min-w-0 max-w-[220px] truncate text-right [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)] max-[560px]:col-start-1 max-[560px]:row-start-auto max-[560px]:max-w-full max-[560px]:text-left",
  identityGrid: "grid min-w-0 grid-cols-2 gap-2 max-[480px]:grid-cols-1",
  identityItem:
    "grid min-w-0 gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-hairline)] bg-[var(--vui-surface-row)] px-2 py-2",
  identityLabel:
    "[font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  identityValue:
    "min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-sm)] font-bold text-[var(--fg-primary)]",
  teamList: "col-span-full flex min-w-0 flex-wrap gap-1.5 max-[480px]:col-span-1",
  teamChip:
    "inline-flex min-h-6 max-w-full items-center rounded-full border border-[var(--vui-border-hairline)] bg-[var(--vui-surface-row)] px-2 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] [&>span]:truncate",
  healthGrid: "grid min-w-0 grid-cols-2 gap-2",
  healthMetric:
    "grid min-w-0 gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-hairline)] bg-[var(--vui-surface-row)] px-2 py-2",
  healthValue:
    "min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-lg)] font-bold text-[var(--fg-primary)]",
  healthLabel:
    "[font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  attentionList: "grid min-w-0 content-start gap-1",
  attentionItem:
    "grid min-w-0 gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-hairline)] bg-[var(--vui-surface-row)] px-2 py-2",
  attentionTitle: "flex min-w-0 items-center justify-between gap-2",
  attentionCopy:
    "m-0 min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)]",
  empty:
    "m-0 rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] px-3 py-5 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-tertiary)]",
  loading:
    "m-0 animate-pulse rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-3 py-6 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-tertiary)]",
  error:
    "m-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_7%,transparent)] px-3 py-4 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
} as const;

export default styles;
