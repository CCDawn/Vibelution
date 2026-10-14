const routeClass = "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden";
const controlButtonClass =
  "inline-flex w-fit max-w-full items-center justify-center gap-1.5 whitespace-nowrap max-[920px]:!min-h-11";
const fieldSurfaceClass =
  "rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-chat";
const rowButtonSurfaceClass =
  "!h-auto !min-h-[58px] w-full !rounded-[var(--radius-control)] !border-0 !bg-transparent !px-3 !py-2.5 !shadow-none !text-left text-vui-fg-primary hover:!bg-vui-surface-row-hover";
const refreshButtonClass = "max-[920px]:!size-11";
const workspaceClass = "h-full min-h-0 min-w-0 gap-0 max-[920px]:!flex-col max-[920px]:overflow-auto max-[920px]:!overflow-y-auto max-[920px]:[&>[data-vui=split-sidebar]]:!h-[48vh] max-[920px]:[&>[data-vui=split-sidebar]]:!min-h-[380px] max-[920px]:[&>[data-vui=split-sidebar]]:!w-full max-[920px]:[&>[data-vui=split-sidebar]]:!min-w-0 max-[920px]:[&>[data-vui=split-sidebar]]:!max-w-none max-[920px]:[&>[data-vui=split-sidebar]]:!basis-auto max-[920px]:[&>[data-vui=split-main]]:!min-h-[420px] max-[920px]:[&>[data-vui=split-main]]:!shrink-0 max-[920px]:[&>[role=separator]]:!hidden";
const loadingBone =
  "block animate-pulse rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] motion-reduce:animate-none";
const loadingListClass = "grid min-w-0 content-start gap-1";
const loadingRowClass = "grid min-h-11 min-w-0 grid-cols-[28px_minmax(0,1fr)] items-center gap-1 px-1";
const loadingCheckClass =
  "block size-4 animate-pulse rounded-[4px] bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] motion-reduce:animate-none";
const loadingNameClass = `${loadingBone} h-3 w-24`;
const loadingDetailClass = "grid min-w-0 content-start gap-2.5 py-2";
const loadingLineClass = `${loadingBone} h-2.5 w-full`;
const loadingLineShortClass = `${loadingBone} h-2.5 w-[64%]`;
const srOnlyClass = "sr-only";
const panelClass = "min-h-0 min-w-0";
const listPanelClass = `${panelClass} vui-workbench-rail flex h-full flex-col gap-2 overflow-hidden !rounded-none !border-0 !px-2 !pb-2 !pt-3 !shadow-none`;
const detailPanelClass = `${panelClass} grid h-full content-start gap-4 !rounded-none !border-0 !bg-transparent !shadow-none overflow-auto overscroll-contain px-6 py-6 max-[640px]:px-4`;
const panelHeaderClass = "flex min-w-0 shrink-0 items-center justify-between gap-2 [&_h2]:text-vui-micro-13 [&_h2]:font-medium";
const panelEyebrowClass = "m-0 mb-px [font-size:var(--vui-font-xs)] uppercase tracking-[0.07em] text-vui-fg-tertiary";
const panelTitleClass = "m-0 font-[var(--font-display)] text-vui-md leading-[1.2] text-vui-fg-primary";
const detailDescriptionClass = "m-0 mt-2 text-vui-micro-13 leading-relaxed text-vui-fg-secondary";
const searchBoxClass = `flex min-h-8 shrink-0 items-center gap-2 ${fieldSurfaceClass} px-2 text-vui-fg-tertiary max-[920px]:min-h-11`;
const searchInputClass = "min-w-0 !w-full !border-0 !bg-transparent !px-0 !shadow-none text-vui-fg-primary max-[920px]:!min-h-11";
const filterRowClass = "flex shrink-0 flex-wrap gap-1";
const filterTabsClass = "inline-grid w-fit max-w-full min-w-0 gap-0";
const filterTabsListClass = "inline-flex min-w-0 max-w-full flex-wrap items-center gap-1 border-0 bg-transparent p-0";
const filterTabsTriggerClass = `${controlButtonClass} !border-transparent !bg-none !shadow-none data-[state=active]:!bg-[var(--vui-selection-bg)]`;
const filterButtonClass = controlButtonClass;
const primaryButtonClass = controlButtonClass;
const bulkToolbarClass = "shrink-0 !border-0 !bg-transparent !p-0 !shadow-none";
const bulkSummaryClass = "inline-flex min-h-7 items-center gap-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary";
const bulkSummaryTitleClass = "text-vui-fg-primary";
const bulkReadOnlyNoteClass = "m-0 shrink-0 border-t border-vui-border-subtle px-3 pt-3 text-vui-2xs leading-relaxed text-vui-fg-tertiary";
const skillListClass = "grid min-h-0 min-w-0 flex-1 content-start gap-1.5 overflow-auto overscroll-contain";
const selectableRowClass = "grid min-w-0 grid-cols-[minmax(0,1fr)] items-center gap-1";
const selectableRowSelectingClass = "!grid-cols-[28px_minmax(0,1fr)] max-[920px]:!grid-cols-[44px_minmax(0,1fr)]";
const rowSelectClass = "relative grid h-11 w-7 cursor-pointer place-items-center rounded-[var(--radius-control)] text-vui-fg-secondary focus-within:shadow-[var(--vui-focus-ring)] max-[920px]:w-11";
const hiddenCheckboxClass = "sr-only";
const skillButtonBaseClass = [
  rowButtonSurfaceClass,
  "!grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3",
].join(" ");
const skillButtonActiveClass = "aria-pressed:!bg-[var(--vui-selection-bg)]";
const skillIconClass = "mt-1 shrink-0 text-vui-fg-tertiary";
const skillCopyClass = "grid min-w-0 gap-1 text-vui-micro-13";
const skillNameClass = "min-w-0 line-clamp-2 break-words font-medium leading-5 text-vui-fg-primary";
const sourceCaptionClass = "truncate text-vui-2xs text-vui-fg-secondary";
const emptyStateClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";
const detailHeaderClass = "flex min-w-0 items-start justify-between gap-3 max-[720px]:flex-wrap";
const commandPanelClass = `grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-t border-vui-border-subtle py-3 max-[720px]:grid-cols-[auto_minmax(0,1fr)]`;
const commandBodyClass = "grid min-w-0 gap-1";
const commandLabelClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const commandCodeClass = "min-w-0 break-all text-vui-micro-13 leading-relaxed text-vui-fg-primary";
const commandFeedbackClass = "[font-size:var(--vui-font-xs)] text-[var(--state-success)]";
const metaGridClass = `grid grid-cols-[110px_minmax(0,1fr)] gap-x-2.5 gap-y-2 py-3 max-[720px]:grid-cols-1`;
const metaLabelClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const metaValueClass = "min-w-0 break-all text-vui-2xs font-normal leading-relaxed text-vui-fg-primary";
const surfacePanelClass = `grid gap-3 border-t border-vui-border-subtle py-3`;
const contentHeaderClass = "flex min-w-0 items-start justify-between gap-3 max-[720px]:flex-wrap";
const contentPreClass = "m-0 min-w-0 whitespace-pre-wrap break-words border-0 bg-transparent text-vui-micro-13 leading-[1.7] text-vui-fg-primary";
const truncatedNoticeClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";
const detailErrorClass = "m-0 flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_34%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-2.5 py-2 [font-size:var(--vui-font-xs)] leading-[1.4] text-[var(--state-error)]";
const detailErrorRetryClass = "max-[920px]:!min-h-11";
const rootRowClass = "grid min-w-0 grid-cols-[90px_minmax(0,1fr)] items-center gap-2.5 max-[720px]:grid-cols-1 max-[720px]:gap-1";
const rootSourceClass = "[font-size:var(--vui-font-xs)] text-vui-fg-tertiary";
const rootPathClass = "min-w-0 break-all text-vui-2xs leading-relaxed";
const emptyDetailClass = "grid min-h-[190px] place-items-center !border-0 !bg-transparent !shadow-none p-4 text-center max-[920px]:min-h-24 max-[920px]:p-3";
const emptyDetailTextClass = "m-0 [font-size:var(--vui-font-xs)] leading-[1.3] text-vui-fg-secondary";

const metadataSummaryClass = "cursor-pointer py-2 text-vui-micro-13 text-vui-fg-secondary max-[920px]:min-h-11";

const styles = {
  metadataSummaryClass,
  routeClass,
  refreshButtonClass,
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
  filterTabsClass,
  filterTabsListClass,
  filterTabsTriggerClass,
  filterButtonClass,
  primaryButtonClass,
  bulkToolbarClass,
  bulkSummaryClass,
  bulkSummaryTitleClass,
  bulkReadOnlyNoteClass,
  skillListClass,
  loadingListClass,
  loadingRowClass,
  loadingCheckClass,
  loadingNameClass,
  loadingDetailClass,
  loadingLineClass,
  loadingLineShortClass,
  srOnlyClass,
  selectableRowClass,
  selectableRowSelectingClass,
  rowSelectClass,
  hiddenCheckboxClass,
  skillButtonBaseClass,
  skillButtonActiveClass,
  skillIconClass,
  skillCopyClass,
  skillNameClass,
  sourceCaptionClass,
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
  detailErrorClass,
  detailErrorRetryClass,
  rootRowClass,
  rootSourceClass,
  rootPathClass,
  emptyDetailClass,
  emptyDetailTextClass,
} as const;

export default styles;
