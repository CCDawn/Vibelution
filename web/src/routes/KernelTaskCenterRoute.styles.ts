const routeClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]";
const headerClass = "mx-2.5 mt-2 min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]";
const headerActionsClass = "flex items-center justify-end gap-2 max-[720px]:items-stretch max-[720px]:flex-col";
const statusFilterClass = "flex min-w-[210px] items-center gap-[7px] text-[var(--vui-font-xs)] text-vui-fg-secondary";
const statusFilterLabelClass = "whitespace-nowrap text-[var(--vui-font-xs)] font-bold";
const iconButtonClass = "h-[34px] w-[34px] min-h-[34px] rounded-lg border border-vui-border-soft bg-[var(--surface-card)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 grid-cols-[minmax(320px,420px)_minmax(0,1fr)] gap-2 px-2.5 pb-2.5 pt-2 max-[1120px]:grid-cols-1 max-[720px]:p-2";
const paneClass = "min-h-0 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)]";
const taskPaneClass = `${paneClass} grid grid-rows-[auto_minmax(0,1fr)]`;
const detailPaneClass = `${paneClass} grid content-start gap-2 overflow-auto p-2`;
const panelHeaderClass = "flex items-center justify-between gap-2 border-b border-vui-border-soft p-2";
const eyebrowClass = "m-0 mb-0.5 text-[var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-vui-fg-tertiary";
const panelCountClass = "text-base text-vui-fg-primary";
const taskListClass = "grid min-h-0 content-start gap-[7px] overflow-auto p-2 max-[1120px]:max-h-[min(38vh,320px)]";
const taskRowClass = "grid !h-auto !min-h-[72px] w-full content-start justify-self-stretch gap-1 overflow-hidden whitespace-normal rounded-md border border-vui-border-soft bg-[var(--surface-panel-muted)] px-2 py-1.5 text-left text-vui-fg-primary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-strong)] [&_[data-slot=vui-button-content]]:grid [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:items-start [&_[data-slot=vui-button-content]]:justify-stretch [&_[data-slot=vui-button-content]]:gap-1 [&_[data-slot=vui-button-label]]:contents [&_[data-slot=vui-button-label]]:overflow-visible [&_[data-slot=vui-button-label]]:whitespace-normal";
const taskRowSelectedClass = "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[var(--surface-active-neutral)] shadow-[var(--vui-shadow-inset-accent)]";
const taskRowTopClass = "grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2";
const taskRowTitleClass = "block min-w-0 truncate";
const taskRowMetaClass = "grid w-full min-w-0 gap-[3px] text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const monoCodeClass = "block w-full min-w-0 break-all text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const detailHeaderClass = "flex items-center justify-between gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-card)] p-2";
const detailTitleClass = "m-0 text-base text-vui-fg-primary";
const summaryGridClass = "grid grid-cols-[repeat(5,minmax(0,1fr))] gap-2 max-[1280px]:grid-cols-3 max-[960px]:grid-cols-2 max-[720px]:grid-cols-1";
const metricClass = "flex min-w-0 items-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-card-subtle)] p-2";
const metricIconClass = "inline-flex text-[var(--accent-cool)]";
const metricBodyClass = "grid min-w-0 gap-0.5";
const metricLabelClass = "text-[var(--vui-font-xs)] uppercase tracking-[0.06em] text-vui-fg-tertiary";
const metricValueClass = "min-w-0 truncate text-[var(--vui-font-xs)] text-vui-fg-primary";
const selectionNoticeClass = "rounded-lg border border-[color-mix(in_srgb,var(--state-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-2 py-[7px] text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const ledgerSectionClass = "grid gap-[7px] rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-panel)_72%,transparent)] p-2";
const ledgerFlowClass = "grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 max-[1280px]:grid-cols-1";
const ledgerBucketClass = "grid min-w-0 content-start gap-[7px] rounded-lg border border-vui-border-soft bg-[var(--surface-card)] p-2";
const sectionHeaderClass = "flex items-center justify-between gap-2";
const sectionTitleClass = "m-0 text-[0.9rem] text-vui-fg-primary";
const sectionCountClass = "text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const deliveryGridClass = "grid gap-1.5";
const deliveryRowClass = "grid gap-1 rounded-lg bg-[var(--surface-card-subtle)] p-[7px]";
const deliveryRowTopClass = "flex items-center justify-between gap-2";
const mutedLineClass = "text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const warningLineClass = "text-[var(--vui-font-xs)] not-italic leading-[1.35] text-[var(--state-warning)]";
const lifecycleSectionClass = "grid gap-[7px] rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-panel)_72%,transparent)] p-2";
const lifecycleTimelineClass = "grid gap-1.5";
const lifecycleRowClass = "grid grid-cols-[14px_minmax(0,1fr)] gap-[7px] rounded-lg border border-[color-mix(in_srgb,var(--vui-border-subtle)_58%,transparent)] bg-[color-mix(in_srgb,var(--surface-card-subtle)_74%,transparent)] p-2";
const lifecycleDotClass = "mt-[5px] h-[9px] w-[9px] rounded-full bg-vui-fg-tertiary";
const lifecycleTitleClass = "flex items-center justify-between gap-2";
const lifecycleKindClass = "text-[var(--vui-font-xs)] text-vui-fg-primary";
const lifecycleSummaryClass = "m-0 my-[3px] text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const chipsClass = "mt-[5px] flex flex-wrap gap-[5px]";
const chipCodeClass = "rounded-full border border-vui-border-soft bg-[var(--surface-code)] px-1.5 py-[3px] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const refListClass = "mt-[5px] flex flex-wrap gap-[5px]";
const evidenceRefListClass = "mt-[5px] flex flex-wrap gap-[5px]";
const emptyInlineClass = "text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const statusPillBaseClass = "inline-flex min-h-[22px] items-center whitespace-nowrap rounded-full border border-vui-border-soft px-[7px] text-[var(--vui-font-xs)]";
const emptyStateClass = "grid min-h-16 content-start gap-1 rounded-lg border border-dashed border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-card-subtle)_74%,transparent)] p-2.5";
const emptyStateLoadingClass = "border-solid";
const emptyStateErrorClass = "border-[color-mix(in_srgb,var(--state-error)_32%,transparent)]";
const emptyTitleClass = "text-[var(--vui-font-xs)] text-vui-fg-primary";
const emptyDetailClass = "text-[var(--vui-font-xs)] text-vui-fg-secondary";

const styles = {
  routeClass,
  headerClass,
  headerActionsClass,
  statusFilterClass,
  statusFilterLabelClass,
  iconButtonClass,
  workspaceClass,
  paneClass,
  taskPaneClass,
  detailPaneClass,
  panelHeaderClass,
  eyebrowClass,
  panelCountClass,
  taskListClass,
  taskRowClass,
  taskRowSelectedClass,
  taskRowTopClass,
  taskRowTitleClass,
  taskRowMetaClass,
  monoCodeClass,
  detailHeaderClass,
  detailTitleClass,
  summaryGridClass,
  metricClass,
  metricIconClass,
  metricBodyClass,
  metricLabelClass,
  metricValueClass,
  selectionNoticeClass,
  ledgerSectionClass,
  ledgerFlowClass,
  ledgerBucketClass,
  sectionHeaderClass,
  sectionTitleClass,
  sectionCountClass,
  deliveryGridClass,
  deliveryRowClass,
  deliveryRowTopClass,
  mutedLineClass,
  warningLineClass,
  lifecycleSectionClass,
  lifecycleTimelineClass,
  lifecycleRowClass,
  lifecycleDotClass,
  lifecycleTitleClass,
  lifecycleKindClass,
  lifecycleSummaryClass,
  chipsClass,
  chipCodeClass,
  refListClass,
  evidenceRefListClass,
  emptyInlineClass,
  statusPillBaseClass,
  emptyStateClass,
  emptyStateLoadingClass,
  emptyStateErrorClass,
  emptyTitleClass,
  emptyDetailClass,
} as const;

export default styles;
