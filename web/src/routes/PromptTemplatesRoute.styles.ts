const routeClass = "grid h-full min-h-0 min-w-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden";
const headerClass = "mx-2 mt-1.5 min-h-9 min-w-0 border-[var(--vui-border-subtle)] !bg-transparent !shadow-none !backdrop-blur-none";
const headerActionsClass = "inline-flex min-w-0 items-center justify-end gap-1.5";
const controlButtonClass =
  "inline-flex min-h-[26px] w-fit max-w-full items-center justify-center gap-1.5 whitespace-nowrap rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-soft)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_72%,transparent)] px-2 py-[3px] [font-size:var(--vui-font-xs)] text-vui-fg-secondary hover:border-[color-mix(in_srgb,var(--border-strong)_78%,transparent)] hover:bg-[var(--vui-control-muted-hover)] hover:text-vui-fg-primary disabled:opacity-55";
const fieldSurfaceClass =
  "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-soft)_76%,transparent)] bg-[color-mix(in_srgb,var(--surface-input-strong)_86%,transparent)]";
const rowButtonSurfaceClass =
  "block w-full rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-soft)_74%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_78%,transparent)] px-[9px] py-2 text-left text-vui-fg-primary hover:border-[color-mix(in_srgb,var(--border-strong)_78%,transparent)] hover:bg-[color-mix(in_srgb,var(--vui-surface-row)_88%,transparent)]";
const pillSurfaceClass =
  "inline-flex min-h-5 max-w-full items-center justify-center rounded-full border border-[color-mix(in_srgb,var(--vui-border-soft)_74%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_72%,transparent)] px-1.5 [font-size:var(--vui-font-xs)]";
const refreshButtonClass = `${controlButtonClass} h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] p-0`;
const returnButtonClass = `${controlButtonClass} gap-[5px] text-[var(--accent-cool)] no-underline`;
const controlStripClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-1.5 px-3 pt-1 max-[980px]:grid-cols-1";
const managementNavClass = "m-0";
const summaryStripClass = "min-w-0 overflow-hidden rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] bg-vui-surface-toolbar p-1 [&_[data-vui=status-strip-item]]:min-w-0 [&_[data-vui=status-strip-item]]:grid-cols-[auto_minmax(0,1fr)] [&_[data-vui=status-strip-item]]:rounded-[var(--radius-control)] [&_[data-vui=status-strip-item]]:bg-transparent [&_[data-vui=status-strip-item]]:font-normal [&_[data-vui=status-strip-item]]:shadow-none [&_[data-vui=status-strip-item]_span:last-child]:min-w-0 [&_[data-vui=status-strip-item]_span:last-child]:truncate";
const summaryLabelClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const summaryValueClass = "min-w-0 truncate [font-size:var(--vui-font-xs)] text-vui-fg-primary";
const workspaceClass = "grid h-full min-h-0 min-w-0 grid-cols-[clamp(260px,26vw,380px)_minmax(0,1fr)] gap-1.5 overflow-hidden px-2 pb-2 pt-1.5 max-[980px]:grid-cols-1 max-[980px]:content-start max-[980px]:overflow-auto";
const panelBaseClass = "grid min-h-0 min-w-0 content-start gap-2 overflow-hidden";
const listPanelClass = `${panelBaseClass} grid-rows-[auto_auto_auto_auto_minmax(0,1fr)] max-[980px]:max-h-[44vh]`;
const editorPanelClass = `${panelBaseClass} grid-rows-[auto_auto_auto_minmax(260px,1fr)_minmax(112px,auto)_auto] content-stretch max-[980px]:grid-rows-[auto_auto_auto_minmax(180px,0.8fr)_auto_auto] max-[980px]:overflow-auto`;
const editorPanelFocusedClass = "border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--border-soft))]";
const panelHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const panelEyebrowClass = "m-0 mb-px [font-size:var(--vui-font-xs)] uppercase tracking-[0.07em] text-vui-fg-tertiary";
const panelTitleClass = "m-0 font-[var(--font-display)] text-base leading-[1.2] text-vui-fg-primary";
const panelDescriptionClass = "m-0 mt-0.5 [font-size:var(--vui-font-xs)] leading-[1.28] text-vui-fg-secondary";
const searchBoxClass = `flex min-h-8 items-center gap-2 ${fieldSurfaceClass} px-2 text-vui-fg-tertiary`;
const searchInputClass = "min-w-0 w-full border-0 bg-transparent text-vui-fg-primary outline-0";
const filterRowClass = "flex flex-wrap gap-[5px]";
const filterButtonClass = controlButtonClass;
const filterButtonActiveClass = `${filterButtonClass} border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm-2)]`;
const primaryButtonClass = `${controlButtonClass} border-[color-mix(in_srgb,var(--accent-warm)_34%,var(--border-soft))] text-[var(--accent-warm-2)]`;
const secondaryButtonClass = controlButtonClass;
const bulkActionBarClass = "grid min-w-0 grid-cols-[auto_auto_minmax(118px,1fr)] items-center justify-items-start gap-[5px] max-[980px]:grid-cols-1";
const bulkSummaryClass = "inline-flex min-h-[26px] min-w-0 items-center gap-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary";
const bulkSummaryTitleClass = "text-vui-fg-primary";
const bulkSelectFieldClass = "inline-flex min-h-[26px] w-fit max-w-full min-w-0 items-center gap-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary";
const bulkSelectClass = `min-h-[26px] min-w-0 max-w-full flex-[1_1_96px] ${fieldSurfaceClass} font-inherit text-vui-fg-primary`;
const templateListClass = "grid min-h-0 content-start gap-1.5 overflow-auto pr-1";
const selectableRowClass = "grid min-w-0 grid-cols-[28px_minmax(0,1fr)] items-center gap-[5px]";
const selectableRowLinkedClass = "rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--accent-cool)_5%,transparent)]";
const rowSelectClass = `grid h-9 w-7 cursor-pointer place-items-center ${fieldSurfaceClass} text-vui-fg-secondary hover:border-[var(--border-strong)] hover:text-[var(--accent-warm-2)]`;
const linkedBorderClass = "border-[color-mix(in_srgb,var(--accent-cool)_44%,var(--border-soft))]";
const hiddenCheckboxClass = "pointer-events-none absolute h-px w-px opacity-0";
const templateButtonBaseClass = [
  rowButtonSurfaceClass,
  "[&_[data-slot=vui-button-content]]:w-full",
  "[&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:gap-[5px]",
].join(" ");
const templateButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[var(--surface-active-neutral)] shadow-[var(--vui-shadow-inset-accent)]";
const templateMainClass = "grid min-w-0 gap-0.5 [&_*]:min-w-0 [&_*]:truncate";
const templateMetaClass =
  "flex flex-wrap gap-1 [&_span]:inline-flex [&_span]:min-h-5 [&_span]:max-w-full [&_span]:items-center [&_span]:justify-center [&_span]:rounded-full [&_span]:border [&_span]:border-[color-mix(in_srgb,var(--vui-border-soft)_74%,transparent)] [&_span]:bg-[color-mix(in_srgb,var(--vui-surface-row)_72%,transparent)] [&_span]:px-1.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary";
const categoryPillClass = `${pillSurfaceClass} text-[var(--accent-cool-2)]`;
const editorHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const editorMetaClass = "grid grid-cols-3 gap-1.5 max-[980px]:grid-cols-1";
const detailRowClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2 gap-y-0 border-0 border-b border-[color-mix(in_srgb,var(--border-soft)_62%,transparent)] bg-transparent px-0 py-[5px] last:border-b-0";
const detailLabelClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const detailValueClass = "min-w-0 truncate [font-size:var(--vui-font-xs)] text-vui-fg-primary";
const fieldClass = "grid min-w-0 gap-[5px]";
const fieldLabelClass = "[font-size:var(--vui-font-xs)] font-bold text-vui-fg-tertiary";
const fieldInputClass = `min-h-8 w-full min-w-0 ${fieldSurfaceClass} px-2 text-vui-fg-primary`;
const nameFieldClass = "self-start";
const contentFieldClass = "grid min-h-0 content-stretch grid-rows-[auto_minmax(0,1fr)] overflow-hidden";
const contentTextareaClass = `h-full min-h-0 w-full min-w-0 resize-none self-stretch ${fieldSurfaceClass} p-2.5 font-[var(--font-mono)] [font-size:var(--vui-font-xs)] leading-[1.5] text-vui-fg-primary`;
const bottomGridClass = "grid min-h-0 grid-cols-[minmax(0,1fr)_clamp(240px,22vw,340px)] gap-2 max-[980px]:grid-cols-1";
const detailCardClass = "grid min-h-0 min-w-0 content-start gap-1.5 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--border-soft)_64%,transparent)] bg-transparent p-2 grid-rows-[auto_minmax(0,1fr)_auto]";
const agentListClass = "grid min-h-0 min-w-0 content-start gap-1.5 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--border-soft)_64%,transparent)] bg-transparent p-2";
const contentHeaderClass = "flex min-w-0 items-center justify-between gap-3";
const cardTitleClass = "m-0 font-[var(--font-display)] text-[0.92rem] text-vui-fg-primary";
const helperTextClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";
const detailCardHelperClass = `${helperTextClass} max-h-[58px] overflow-auto`;
const agentRowsClass = "grid max-h-[140px] gap-[5px] overflow-auto";
const agentItemClass = "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 gap-y-1 rounded-[var(--radius-control)] border border-vui-border-soft bg-[color-mix(in_srgb,var(--vui-surface-row)_78%,transparent)] px-2 py-1.5 [&_*]:min-w-0";
const agentItemLinkedClass = "border-[color-mix(in_srgb,var(--accent-cool)_46%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))]";
const agentNameClass = "truncate";
const agentCodeClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const agentMetaClass = "truncate [font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const actionsClass = "flex flex-wrap justify-end gap-2";
const noticeClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-[var(--state-success)]";
const errorTextClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-[var(--state-danger)]";
const emptyStateClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";

const styles = {
  routeClass,
  headerClass,
  headerActionsClass,
  refreshButtonClass,
  returnButtonClass,
  controlStripClass,
  managementNavClass,
  summaryStripClass,
  summaryLabelClass,
  summaryValueClass,
  workspaceClass,
  panelBaseClass,
  listPanelClass,
  editorPanelClass,
  editorPanelFocusedClass,
  panelHeaderClass,
  panelEyebrowClass,
  panelTitleClass,
  panelDescriptionClass,
  searchBoxClass,
  searchInputClass,
  filterRowClass,
  filterButtonClass,
  filterButtonActiveClass,
  primaryButtonClass,
  secondaryButtonClass,
  bulkActionBarClass,
  bulkSummaryClass,
  bulkSummaryTitleClass,
  bulkSelectFieldClass,
  bulkSelectClass,
  templateListClass,
  selectableRowClass,
  selectableRowLinkedClass,
  rowSelectClass,
  linkedBorderClass,
  hiddenCheckboxClass,
  templateButtonBaseClass,
  templateButtonActiveClass,
  templateMainClass,
  templateMetaClass,
  categoryPillClass,
  editorHeaderClass,
  editorMetaClass,
  detailRowClass,
  detailLabelClass,
  detailValueClass,
  fieldClass,
  fieldLabelClass,
  fieldInputClass,
  nameFieldClass,
  contentFieldClass,
  contentTextareaClass,
  bottomGridClass,
  detailCardClass,
  agentListClass,
  contentHeaderClass,
  cardTitleClass,
  helperTextClass,
  detailCardHelperClass,
  agentRowsClass,
  agentItemClass,
  agentItemLinkedClass,
  agentNameClass,
  agentCodeClass,
  agentMetaClass,
  actionsClass,
  noticeClass,
  errorTextClass,
  emptyStateClass,
} as const;

export default styles;
