const panelSurface =
  "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_64%,transparent)]";
const cardSurface =
  "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_68%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_56%,transparent)] p-2";
const rowSurface =
  "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_58%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_74%,transparent)] p-2";

const routeClass = "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] overflow-hidden overflow-x-hidden";
const headerClass = "mx-2 mt-1.5 min-w-0 border-[color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)]";
const headerActionsClass = "flex flex-wrap items-center justify-end gap-2 max-[720px]:items-stretch max-[720px]:flex-col";
const statusFilterClass = "flex w-fit max-w-full min-w-[210px] items-center gap-[7px] [font-size:var(--vui-font-xs)] text-vui-fg-secondary";
const statusFilterLabelClass = "whitespace-nowrap [font-size:var(--vui-font-xs)] font-bold";
const iconButtonClass = "h-[34px] w-[34px] min-h-[34px] rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-soft)_78%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_74%,transparent)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[color-mix(in_srgb,var(--vui-control-muted-hover)_84%,transparent)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 min-w-0 max-w-full grid-cols-[clamp(280px,28vw,400px)_minmax(0,1fr)] gap-2 overflow-hidden overflow-x-hidden px-2 pb-2 pt-1.5 max-[1120px]:grid-cols-1 max-[1120px]:grid-rows-[minmax(180px,32vh)_minmax(0,1fr)] max-[720px]:grid-cols-[minmax(0,1fr)] max-[720px]:grid-rows-[minmax(180px,34vh)_minmax(360px,1fr)] max-[720px]:p-2";
const paneClass = `min-h-0 min-w-0 overflow-hidden ${panelSurface}`;
const taskPaneClass = `${paneClass} grid grid-rows-[auto_minmax(0,1fr)]`;
const detailPaneClass = `${paneClass} grid max-w-full grid-cols-[minmax(0,1fr)_clamp(280px,26vw,380px)] grid-rows-[minmax(0,1fr)] gap-2 p-2 max-[1280px]:grid-cols-1 max-[1280px]:grid-rows-[minmax(0,0.98fr)_minmax(240px,0.82fr)] max-[720px]:grid-rows-none max-[720px]:overflow-y-auto max-[720px]:overflow-x-hidden`;
const detailContentClass = "grid min-h-0 min-w-0 max-w-full content-start gap-2 overflow-auto overflow-x-hidden pr-1";
const panelHeaderClass = "flex items-center justify-between gap-2 border-b border-vui-border-soft p-2";
const eyebrowClass = "m-0 mb-0.5 [font-size:var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-vui-fg-tertiary";
const panelCountClass = "text-base text-vui-fg-primary";
const taskListClass = "grid min-h-0 min-w-0 max-w-full content-start gap-[7px] overflow-auto overflow-x-hidden p-2 max-[1120px]:max-h-[min(38vh,320px)]";
const taskRowClass = "grid !h-auto !min-h-[72px] w-full min-w-0 max-w-full content-start justify-self-stretch gap-1 overflow-hidden whitespace-normal rounded-[var(--radius-control)] border border-vui-border-soft bg-[color-mix(in_srgb,var(--vui-surface-row)_74%,transparent)] px-2 py-1.5 text-left text-vui-fg-primary hover:border-[var(--border-strong)] hover:bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_84%,transparent)] [&_[data-slot=vui-button-content]]:grid [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:items-start [&_[data-slot=vui-button-content]]:justify-stretch [&_[data-slot=vui-button-content]]:gap-1 [&_[data-slot=vui-button-label]]:contents [&_[data-slot=vui-button-label]]:overflow-visible [&_[data-slot=vui-button-label]]:whitespace-normal";
const taskRowSelectedClass = "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[var(--surface-active-neutral)] shadow-[var(--vui-shadow-inset-accent)]";
const taskRowTopClass = "grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2";
const taskRowTitleClass = "block min-w-0 truncate";
const taskRowMetaClass = "grid w-full min-w-0 gap-[3px] [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const monoCodeClass = "block w-full min-w-0 break-all [font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const detailHeaderClass = `flex min-w-0 max-w-full items-center justify-between gap-2 ${cardSurface}`;
const detailTitleWrapClass = "min-w-0";
const detailTitleClass = "m-0 min-w-0 truncate text-base text-vui-fg-primary";
const summaryGridClass = "min-w-0 max-w-full overflow-x-auto";
const selectionNoticeClass = "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-2 py-[7px] [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const ledgerSectionClass = "grid min-w-0 gap-[7px] border-t border-vui-border-soft pt-2";
const ledgerFlowClass = "grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 max-[1280px]:grid-cols-1";
const ledgerBucketClass = "grid min-w-0 content-start gap-[7px]";
const sectionHeaderClass = "flex items-center justify-between gap-2";
const sectionTitleClass = "m-0 text-[0.9rem] text-vui-fg-primary";
const sectionCountClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const deliveryGridClass = "grid min-h-0 min-w-0 max-w-full content-start gap-1.5 overflow-auto overflow-x-hidden pr-1";
const deliveryRowClass = "grid min-w-0 max-w-full gap-1 rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--vui-surface-row)_64%,transparent)] p-[7px]";
const deliveryRowTopClass = "grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2 [&>strong]:min-w-0 [&>strong]:truncate";
const mutedLineClass = "min-w-0 break-words [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const warningLineClass = "min-w-0 break-words [font-size:var(--vui-font-xs)] not-italic leading-[1.35] text-[var(--state-warning)]";
const lifecycleSectionClass = "grid min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] gap-[7px] overflow-hidden rounded-[var(--radius-panel)] border border-vui-border-soft bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] p-2";
const lifecycleTimelineClass = "grid min-h-0 min-w-0 max-w-full content-start gap-1.5 overflow-auto overflow-x-hidden pr-1";
const lifecycleRowClass = `grid grid-cols-[14px_minmax(0,1fr)] gap-[7px] ${rowSurface}`;
const lifecycleDotClass = "mt-[5px] h-[9px] w-[9px] rounded-full bg-vui-fg-tertiary";
const lifecycleTitleClass = "flex items-center justify-between gap-2";
const lifecycleKindClass = "[font-size:var(--vui-font-xs)] text-vui-fg-primary";
const lifecycleSummaryClass = "m-0 my-[3px] min-w-0 break-words [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const chipsClass = "mt-[5px] flex flex-wrap gap-[5px]";
const chipCodeClass = "max-w-full overflow-hidden truncate whitespace-nowrap rounded-full border border-vui-border-soft bg-[var(--surface-code)] px-1.5 py-[3px] [font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const refListClass = "mt-[5px] flex min-w-0 max-w-full flex-wrap gap-[5px]";
const evidenceRefListClass = "mt-[5px] flex min-w-0 max-w-full flex-wrap gap-[5px]";
const emptyInlineClass = "[font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const statusPillBaseClass = "inline-flex min-h-[22px] items-center whitespace-nowrap rounded-full border border-vui-border-soft px-[7px] [font-size:var(--vui-font-xs)]";
const emptyStateClass = "grid min-h-16 content-start gap-1 break-words rounded-[var(--radius-panel)] border border-dashed border-vui-border-soft bg-[color-mix(in_srgb,var(--vui-surface-row)_74%,transparent)] p-2.5";

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
  detailContentClass,
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
  detailTitleWrapClass,
  detailTitleClass,
  summaryGridClass,
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
} as const;

export default styles;
