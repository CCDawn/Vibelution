import { vuiWorkspaceFillClass } from "../../design/vuiSurfaceRecipes";

const panelSurface = "!rounded-none !border-0 !shadow-none";
const cardSurface = "rounded-[var(--radius-control)] border-0 bg-vui-surface-row p-2 shadow-none";
// Directory row anatomy (ZCode SubagentDirectorySidePane.tsx:64-102):
// [neutral status icon] [title + status word / kind + summary] [relative time].
const rowSurface = "!rounded-[var(--radius-control)] !border-0 !bg-vui-surface-row px-2 py-1.5 !shadow-none text-vui-fg-primary hover:!bg-[var(--vui-surface-row-hover)]";
const rowGrid = "grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 whitespace-normal text-left";

const routeClass = "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] overflow-hidden overflow-x-hidden !bg-vui-surface-panel";
const headerClass = "mx-2 mt-1.5 min-w-0 !rounded-none !border-0 !bg-transparent !shadow-none !backdrop-blur-none";
const headerActionsClass = "flex flex-wrap items-center justify-end gap-2 max-[720px]:items-stretch max-[720px]:flex-col";
const kindFilterClass = "flex w-fit max-w-full min-w-[190px] items-center gap-2 [font-size:var(--vui-font-xs)] text-vui-fg-secondary";
const kindFilterLabelClass = "whitespace-nowrap [font-size:var(--vui-font-xs)] font-bold";
const iconButtonClass = "h-[var(--vui-control-height-md)] w-[var(--vui-control-height-md)] min-h-[var(--vui-control-height-md)] rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-soft)_78%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_74%,transparent)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[color-mix(in_srgb,var(--vui-control-muted-hover)_84%,transparent)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 min-w-0 max-w-full grid-cols-[clamp(300px,28vw,420px)_minmax(0,1fr)] gap-2 overflow-hidden overflow-x-hidden px-2 pb-2 pt-1.5 max-[1120px]:grid-cols-1 max-[1120px]:grid-rows-[minmax(180px,32vh)_minmax(0,1fr)] max-[720px]:grid-cols-[minmax(0,1fr)] max-[720px]:grid-rows-[minmax(180px,34vh)_minmax(360px,1fr)] max-[720px]:p-2";
const paneClass = `min-h-0 min-w-0 overflow-hidden ${panelSurface}`;
const taskPaneClass = `${paneClass} grid grid-rows-[auto_minmax(0,1fr)]`;
const panelHeaderClass = "flex items-center justify-between gap-2 px-2 pb-1 pt-2";
const eyebrowClass = "m-0 mb-0.5 [font-size:var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-vui-fg-tertiary";
const panelCountClass = "text-vui-md text-vui-fg-primary";
const taskListClass = "grid auto-rows-max min-h-0 min-w-0 max-w-full content-start gap-2 overflow-auto overflow-x-hidden p-2 max-[1120px]:max-h-[min(38vh,320px)]";
const taskSectionClass = "grid min-w-0 gap-1.5";
const taskSectionHeaderClass = "flex items-center justify-between gap-2 px-0.5";
const taskSectionTitleClass = "m-0 text-vui-xs text-vui-fg-primary";
const taskSectionCountClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const taskRowClass = `!h-auto !min-h-[56px] max-w-full ${rowSurface} ${rowGrid} overflow-hidden`;
const taskRowSelectedClass = "!bg-[var(--vui-surface-row-hover)] shadow-[var(--vui-shadow-inset-accent)]";
const taskRowLiveClass = `relative !h-auto !min-h-[56px] grid max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5 ${rowSurface}`;
const taskRowOverlayClass = "absolute inset-0 z-0 !rounded-[var(--radius-control)]";
const taskRowContentClass = `pointer-events-none relative z-[1] min-w-0 ${rowGrid}`;
const taskRowStopClass = "!h-7 !min-h-7 !w-7 !min-w-7 !justify-center !px-0 !bg-transparent pointer-events-auto relative z-[2] shrink-0 text-vui-fg-tertiary hover:!bg-[var(--vui-surface-row-hover)] hover:text-vui-fg-primary";
const taskRowIconClass = "mt-0.5 shrink-0 text-vui-fg-tertiary";
const taskRowIconSpinClass = "animate-spin";
const taskRowMainClass = "grid min-w-0 content-start gap-0.5";
const taskRowTopClass = "flex min-w-0 items-center gap-2";
const taskRowTitleClass = "min-w-0 truncate text-left [font-size:var(--vui-font-xs)] font-medium text-vui-fg-primary";
const taskRowStatusWordClass = "shrink-0 [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-tertiary";
const taskRowMetaClass = "flex min-w-0 items-center gap-2 [font-size:var(--vui-font-xs)] leading-[1.35]";
const taskRowKindClass = "shrink-0 text-vui-fg-secondary";
const taskRowSummaryClass = "min-w-0 truncate text-vui-fg-secondary";
const taskRowTimeClass = "shrink-0 self-start pt-0.5 text-right [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-tertiary";
const loadMoreRowClass = "grid min-w-0 justify-items-start px-0.5";
const detailPaneClass = `${paneClass} grid max-w-full grid-rows-[minmax(0,1fr)] p-2`;
const detailContentClass = "grid min-h-0 min-w-0 max-w-full content-start gap-2 overflow-auto overflow-x-hidden pr-1";
const detailHeaderClass = `flex min-w-0 max-w-full items-center justify-between gap-2 ${cardSurface}`;
const detailTitleWrapClass = "min-w-0";
const detailTitleClass = "m-0 min-w-0 break-words [overflow-wrap:anywhere] text-vui-md text-vui-fg-primary";
const statusPillBaseClass = "!min-h-[22px] max-w-full truncate !px-2 ![font-size:var(--vui-font-xs)]";
const summaryGridClass = "min-w-0 max-w-full overflow-x-auto";
const mutedLineClass = "min-w-0 break-words [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const monoCodeClass = "block w-full min-w-0 break-all [font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const detailActionsClass = "flex min-w-0 max-w-full flex-wrap items-center gap-2";
const summaryTextClass = "m-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-[var(--radius-control)] border-0 bg-vui-surface-row p-2 [font-size:var(--vui-font-xs)] leading-[1.5] text-vui-fg-secondary shadow-none";
const timelineSectionClass = `grid min-w-0 gap-1.5 rounded-[var(--radius-control)] border-0 bg-vui-surface-row p-2 shadow-none`;
const timelineRowClass = "grid min-w-0 max-w-full grid-cols-[auto_minmax(0,1fr)] items-baseline gap-2";
const timelineLabelClass = "min-w-0 break-words [overflow-wrap:anywhere] [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const emptyStateClass = "grid min-h-16 content-start gap-1 break-words rounded-[var(--radius-control)] !border-0 bg-vui-surface-row p-2.5 shadow-none";
const loadingRegionClass = "min-h-0 min-w-0 [&_[aria-hidden=true]>div]:!border-0";
const detailErrorClass = "min-w-0 max-w-full";
// Embedded read-only child-session stream: the head cluster stays fixed while
// the stream body takes the remaining height and scrolls inside itself
// (ChatSessionWorkspacePanel owns the inner conversationBody scroll).
const detailStreamLayoutClass = "flex min-h-0 min-w-0 max-w-full flex-col gap-2 overflow-hidden";
const detailStreamHeadClass = "grid min-w-0 max-w-full shrink-0 content-start gap-2";
const detailStreamBodyClass = "flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-hidden overflow-x-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-vui-surface-panel";

const styles = {
  routeClass,
  headerClass,
  headerActionsClass,
  kindFilterClass,
  kindFilterLabelClass,
  iconButtonClass,
  workspaceClass,
  paneClass,
  taskPaneClass,
  panelHeaderClass,
  eyebrowClass,
  panelCountClass,
  taskListClass,
  taskSectionClass,
  taskSectionHeaderClass,
  taskSectionTitleClass,
  taskSectionCountClass,
  taskRowClass,
  taskRowSelectedClass,
  taskRowLiveClass,
  taskRowOverlayClass,
  taskRowContentClass,
  taskRowStopClass,
  taskRowIconClass,
  taskRowIconSpinClass,
  taskRowMainClass,
  taskRowTopClass,
  taskRowTitleClass,
  taskRowStatusWordClass,
  taskRowMetaClass,
  taskRowKindClass,
  taskRowSummaryClass,
  taskRowTimeClass,
  loadMoreRowClass,
  detailPaneClass,
  detailContentClass,
  detailHeaderClass,
  detailTitleWrapClass,
  detailTitleClass,
  statusPillBaseClass,
  summaryGridClass,
  mutedLineClass,
  monoCodeClass,
  detailActionsClass,
  summaryTextClass,
  timelineSectionClass,
  timelineRowClass,
  timelineLabelClass,
  emptyStateClass,
  loadingRegionClass,
  detailErrorClass,
  detailStreamLayoutClass,
  detailStreamHeadClass,
  detailStreamBodyClass,
  vuiWorkspaceFillClass,
} as const;

export default styles;
