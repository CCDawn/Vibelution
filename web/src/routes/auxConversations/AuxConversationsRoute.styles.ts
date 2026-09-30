import { vuiWorkspaceFillClass } from "../../design/vuiSurfaceRecipes";

const panelSurface = "!rounded-none !border-0 !shadow-none";
const cardSurface = "rounded-[var(--radius-control)] border-0 bg-vui-surface-row p-2 shadow-none";
const rowSurface = "rounded-[var(--radius-control)] border-0 bg-vui-surface-row p-2 shadow-none";

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
const taskRowClass = "grid !h-auto !min-h-[60px] w-full min-w-0 max-w-full content-start justify-self-stretch gap-1 overflow-hidden whitespace-normal !rounded-[var(--radius-control)] !border-0 !bg-vui-surface-row px-2 py-1.5 text-left text-vui-fg-primary !shadow-none hover:!bg-[var(--vui-surface-row-hover)]";
const taskRowSelectedClass = "!bg-[var(--vui-surface-row-hover)] shadow-[var(--vui-shadow-inset-accent)]";
const taskRowTopClass = "grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2";
const taskRowTitleClass = "min-w-0 truncate text-left [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-primary";
const taskRowMetaClass = "grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const statusDotChipClass = "!min-h-4 !w-4 !min-w-4 !justify-center !px-0 !text-vui-micro-10";
const kindChipClass = "max-w-full truncate !min-h-[20px] !px-1.5 ![font-size:var(--vui-font-xs)]";
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
  taskRowTopClass,
  taskRowTitleClass,
  taskRowMetaClass,
  statusDotChipClass,
  kindChipClass,
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
  vuiWorkspaceFillClass,
} as const;

export default styles;
