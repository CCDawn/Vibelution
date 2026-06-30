const routeClass = "grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] bg-[color-mix(in_srgb,var(--surface-page)_94%,var(--bg-canvas))]";
const headerClass = "mx-2.5 mt-2 min-h-9 min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]";
const refreshButtonClass = "h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-h-[26px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card)] p-0 text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary disabled:opacity-55";
const controlStripClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-1.5 px-3 pt-1 max-[920px]:grid-cols-1";
const managementNavClass = "m-0";
const summaryGridClass = "grid min-w-0 grid-cols-4 overflow-hidden rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color-mix(in_srgb,var(--surface-panel)_90%,var(--surface-card))] max-[920px]:grid-cols-1";
const summaryCardClass = "grid min-h-[26px] min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-[5px] border-0 border-r border-[color-mix(in_srgb,var(--border-soft)_58%,transparent)] bg-transparent px-2 py-[3px] last:border-r-0";
const summaryLabelClass = "text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const summaryValueClass = "min-w-0 truncate text-[var(--vui-font-xs)] text-vui-fg-primary";
const workspaceClass = "grid min-h-0 grid-cols-[minmax(260px,340px)_minmax(440px,1fr)] gap-1.5 px-2.5 pb-2 pt-1.5 max-[920px]:grid-cols-1 max-[920px]:content-start max-[920px]:overflow-auto";
const panelClass = "grid min-h-0 min-w-0 content-start gap-[9px] rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2.5";
const listPanelClass = `${panelClass} grid-rows-[auto_auto_auto_minmax(0,1fr)]`;
const detailPanelClass = `${panelClass} overflow-auto`;
const panelHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const panelEyebrowClass = "m-0 mb-px text-[var(--vui-font-xs)] uppercase tracking-[0.07em] text-vui-fg-tertiary";
const panelTitleClass = "m-0 font-[var(--font-display)] text-base leading-[1.2] text-vui-fg-primary";
const detailDescriptionClass = "m-0 mt-[3px] text-[var(--vui-font-xs)] leading-[1.32] text-vui-fg-secondary";
const searchBoxClass = "flex min-h-8 items-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-input-strong)] px-2 text-vui-fg-tertiary";
const searchInputClass = "min-w-0 w-full border-0 bg-transparent text-vui-fg-primary outline-0";
const filterRowClass = "flex flex-wrap gap-[5px]";
const filterButtonClass = "min-h-[26px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card)] px-2 py-[3px] text-[var(--vui-font-xs)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const filterButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm-2)]";
const primaryButtonClass = "min-h-[26px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card)] px-2 py-[3px] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const bulkActionBarClass = "flex min-w-0 flex-wrap items-center gap-[7px] rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-panel)_86%,var(--surface-card))] p-[7px]";
const bulkSummaryClass = "inline-flex min-h-7 items-center gap-1.5 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const bulkSummaryTitleClass = "text-vui-fg-primary";
const bulkReadOnlyNoteClass = "inline-flex min-h-7 max-w-[min(420px,100%)] items-center text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-tertiary";
const skillListClass = "grid min-h-0 content-start gap-1.5 overflow-auto pr-1";
const selectableRowClass = "grid min-w-0 grid-cols-[28px_minmax(0,1fr)] items-center gap-[5px]";
const rowSelectClass = "grid h-9 w-7 cursor-pointer place-items-center rounded-lg border border-vui-border-soft bg-[var(--surface-card)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:text-[var(--accent-warm-2)]";
const hiddenCheckboxClass = "pointer-events-none absolute h-px w-px opacity-0";
const skillButtonBaseClass = [
  "block w-full rounded-lg border border-vui-border-soft bg-[var(--surface-panel-muted)] p-2 text-left text-vui-fg-primary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-strong)]",
  "[&_[data-slot=vui-button-content]]:w-full",
  "[&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:grid-cols-[10px_minmax(0,1fr)_auto] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2",
].join(" ");
const skillButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[var(--surface-active-neutral)] shadow-[var(--vui-shadow-inset-accent)]";
const sourceDotClass = "h-2 w-2 rounded-full bg-[var(--accent-cool)] data-[source=agents]:bg-[var(--accent-warm)] data-[source=other]:bg-vui-fg-tertiary";
const skillCopyClass = "grid min-w-0 gap-0.5";
const skillNameClass = "min-w-0 truncate text-vui-fg-primary";
const skillDescriptionClass = "m-0 min-w-0 truncate text-[var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";
const sourcePillClass = "inline-flex min-h-[21px] items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft px-1.5 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const emptyStateClass = "m-0 text-[var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";
const detailHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const commandPanelClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2.5";
const commandBodyClass = "grid min-w-0 gap-1";
const commandLabelClass = "text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const commandCodeClass = "min-w-0 truncate text-[0.98rem] text-[var(--accent-warm-2)]";
const commandFeedbackClass = "text-[var(--vui-font-xs)] text-[var(--state-success)]";
const metaGridClass = "grid grid-cols-[110px_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 rounded-lg border border-vui-border-soft bg-[var(--surface-card)] p-2.5";
const metaLabelClass = "text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const metaValueClass = "min-w-0 truncate text-[var(--vui-font-xs)] text-vui-fg-primary";
const surfacePanelClass = "grid gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2.5";
const contentHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const contentPreClass = "m-0 max-h-[48vh] overflow-auto rounded-lg border border-vui-border-soft bg-[var(--surface-input-strong)] p-2.5 text-[var(--vui-font-xs)] leading-[1.48] text-vui-fg-primary whitespace-pre-wrap break-words";
const truncatedNoticeClass = "m-0 text-[var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";
const rootRowClass = "grid min-w-0 grid-cols-[90px_minmax(0,1fr)] items-center gap-2.5";
const rootSourceClass = "text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const rootPathClass = "min-w-0 truncate";
const emptyDetailClass = "grid min-h-[190px] place-items-center rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-[18px] text-center max-[920px]:min-h-24 max-[920px]:p-3";
const emptyDetailTextClass = "m-0 text-[var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";

const styles = {
  routeClass,
  headerClass,
  refreshButtonClass,
  controlStripClass,
  managementNavClass,
  summaryGridClass,
  summaryCardClass,
  summaryLabelClass,
  summaryValueClass,
  workspaceClass,
  panelClass,
  listPanelClass,
  detailPanelClass,
  panelHeaderClass,
  panelEyebrowClass,
  panelTitleClass,
  detailDescriptionClass,
  searchBoxClass,
  searchInputClass,
  filterRowClass,
  filterButtonClass,
  filterButtonActiveClass,
  primaryButtonClass,
  bulkActionBarClass,
  bulkSummaryClass,
  bulkSummaryTitleClass,
  bulkReadOnlyNoteClass,
  skillListClass,
  selectableRowClass,
  rowSelectClass,
  hiddenCheckboxClass,
  skillButtonBaseClass,
  skillButtonActiveClass,
  sourceDotClass,
  skillCopyClass,
  skillNameClass,
  skillDescriptionClass,
  sourcePillClass,
  emptyStateClass,
  detailHeaderClass,
  commandPanelClass,
  commandBodyClass,
  commandLabelClass,
  commandCodeClass,
  commandFeedbackClass,
  metaGridClass,
  metaLabelClass,
  metaValueClass,
  surfacePanelClass,
  contentHeaderClass,
  contentPreClass,
  truncatedNoticeClass,
  rootRowClass,
  rootSourceClass,
  rootPathClass,
  emptyDetailClass,
  emptyDetailTextClass,
} as const;

export default styles;
