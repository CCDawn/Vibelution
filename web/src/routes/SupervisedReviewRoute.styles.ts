import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const reviewPanelSurface = `${vuiFlatPanelClass} shadow-none`;
const reviewRowSurface = vuiOpaqueRowClass;
const reviewRowSurfaceSoft = vuiOpaqueRowClass;
const reviewControlSurface =
  "rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted transition hover:border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] hover:bg-vui-control-muted-hover";
const reviewControlButton =
  `inline-flex min-h-8 min-w-0 w-fit max-w-full items-center justify-center gap-2 px-2.5 text-[13px] font-semibold leading-tight text-vui-fg-primary no-underline disabled:cursor-not-allowed disabled:opacity-55 [&_[data-slot=vui-button-content]]:min-w-0 ${reviewControlSurface}`;
const reviewControlButtonActive =
  "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]";
const reviewPrimaryActionButton =
  "inline-flex min-h-8 min-w-0 w-fit max-w-full items-center justify-center gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_16%,var(--vui-control-muted))] px-2.5 text-[13px] font-semibold leading-tight text-[var(--accent-warm-2)] no-underline transition disabled:cursor-not-allowed disabled:opacity-55 [&_[data-slot=vui-button-content]]:min-w-0";
const reviewFormLabel =
  "block [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)]";
const reviewInputTargets =
  "[&_input]:min-h-[34px] [&_input]:w-full [&_input]:rounded-[var(--radius-control)] [&_input]:border [&_input]:border-vui-border-subtle [&_input]:bg-vui-control-muted [&_input]:px-3 [&_input]:font-[inherit] [&_input]:text-vui-fg-primary [&_input]:outline-none [&_input::placeholder]:text-vui-fg-tertiary [&_select]:min-h-[34px] [&_select]:w-full [&_select]:rounded-[var(--radius-control)] [&_select]:border [&_select]:border-vui-border-subtle [&_select]:bg-vui-control-muted [&_select]:px-3 [&_select]:font-[inherit] [&_select]:text-vui-fg-primary [&_select]:outline-none";
const reviewTextAreaTargets =
  "[&_textarea]:min-h-[84px] [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-[var(--radius-control)] [&_textarea]:border [&_textarea]:border-vui-border-subtle [&_textarea]:bg-vui-control-muted [&_textarea]:p-2.5 [&_textarea]:font-[inherit] [&_textarea]:text-vui-fg-primary [&_textarea]:outline-none [&_textarea::placeholder]:text-vui-fg-tertiary";
const reviewFormField = [reviewFormLabel, reviewInputTargets].join(" ");
const reviewTextAreaField = [reviewFormLabel, reviewTextAreaTargets].join(" ");

const styles = {
  page:
    "flex h-full min-h-0 min-w-0 max-w-full flex-col gap-1.5 overflow-hidden overflow-x-hidden px-2 py-1.5 pb-2.5 text-[var(--fg-primary)] max-[980px]:overflow-y-auto max-[980px]:overflow-x-hidden max-[980px]:pb-[18px]",
  toolbar: "flex min-w-0 flex-wrap items-center justify-between gap-[var(--route-topbar-gap)]",
  toolbarIntro: "grid min-w-0 max-w-none flex-1 gap-0.5",
  toolbarControls: "flex flex-wrap items-center justify-end gap-3",
  eyebrow: "m-0 mb-0.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--accent-warm-2)]",
  title: "m-0 whitespace-nowrap text-[length:var(--route-topbar-title-size)] leading-[1.08]",
  subtitle:
    "m-0 max-w-none overflow-hidden text-ellipsis whitespace-nowrap text-[length:var(--route-topbar-subtitle-size)] leading-tight text-[var(--fg-secondary)]",
  summaryStrip: "grid grid-cols-5 gap-[var(--route-summary-gap)] max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  summaryCard:
    `grid min-h-7 min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-1.5 px-2 py-1 ${reviewRowSurfaceSoft} [&_span]:whitespace-nowrap [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:[font-size:var(--vui-font-xs)]`,
  lifecyclePanel:
    `flex min-h-[34px] min-w-0 items-center justify-between gap-2 px-2 py-1.5 max-[980px]:flex-col max-[980px]:items-start ${reviewRowSurfaceSoft}`,
  lifecyclePills: "flex flex-wrap justify-end gap-2 max-[980px]:justify-start",
  workspace:
    `grid min-h-0 min-w-0 max-w-full flex-1 grid-cols-[var(--review-queue-width,380px)_12px_minmax(0,1fr)] overflow-hidden overflow-x-hidden max-[980px]:grid-cols-1 max-[980px]:gap-y-3 max-[980px]:overflow-y-visible max-[980px]:overflow-x-hidden ${vuiWorkspaceFillClass}`,
  resizeHandle:
    "relative min-w-3 cursor-col-resize touch-none border-0 bg-transparent p-0 outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-[3px] before:-translate-x-1/2 before:rounded-[var(--radius-control)] before:bg-[var(--vui-border-subtle)] before:transition before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:before:shadow-none focus-visible:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] focus-visible:before:shadow-none max-[980px]:hidden",
  queuePanel:
    `grid min-h-0 min-w-0 max-w-full grid-rows-[auto_auto_auto_auto_minmax(0,1fr)] gap-2 overflow-hidden p-[9px] max-[980px]:max-h-[min(620px,72vh)] max-[980px]:overflow-hidden ${reviewPanelSurface}`,
  paneCollapsed: "overflow-hidden p-0 invisible",
  detailPanel:
    `flex min-h-0 min-w-0 max-w-full flex-col gap-2.5 overflow-y-auto overflow-x-hidden p-[9px] max-[980px]:overflow-y-visible max-[980px]:overflow-x-hidden ${reviewPanelSurface}`,
  panelHeader: "flex min-w-0 items-start justify-between gap-3.5",
  detailHeader: "flex min-w-0 items-start justify-between gap-3.5 max-[520px]:flex-col",
  sectionHeader: "flex min-w-0 items-start justify-between gap-3.5 max-[520px]:flex-col",
  sectionTitle: "m-0 text-base font-bold leading-snug",
  detailTitle: "m-0 text-base font-bold leading-snug",
  detailLead: "m-0 mt-1.5 leading-snug text-[var(--fg-secondary)]",
  secondaryPill:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted px-2 text-xs font-semibold text-vui-fg-secondary",
  statusBadge:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-transparent px-2 text-xs font-semibold",
  statusPending:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusPositive:
    "border-[color-mix(in_srgb,var(--state-success)_20%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusNegative:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusDiscard: `border-[var(--vui-surface-row)] ${vuiOpaqueRowClass} text-[var(--fg-secondary)]`,
  queueControls: "flex flex-col gap-2.5",
  filterSegmented: "flex flex-wrap items-center gap-1.5",
  decisionSegmented: "flex flex-wrap items-center gap-1.5",
  filterButton: reviewControlButton,
  decisionButton: reviewControlButton,
  filterButtonActive: reviewControlButtonActive,
  decisionButtonActive: reviewControlButtonActive,
  primaryAction: reviewPrimaryActionButton,
  secondaryAction: reviewControlButton,
  compactAction:
    `inline-flex min-h-7 min-w-0 w-fit max-w-full items-center justify-center gap-1.5 overflow-hidden whitespace-nowrap px-2 text-[11px] font-semibold text-vui-fg-primary no-underline disabled:cursor-not-allowed disabled:opacity-55 [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-label]]:truncate ${reviewControlSurface}`,
  dangerAction:
    "border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  searchField:
    "flex min-h-[34px] items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted px-2.5 text-vui-fg-secondary [&_input]:w-full [&_input]:border-0 [&_input]:bg-transparent [&_input]:font-[inherit] [&_input]:text-vui-fg-primary [&_input]:outline-none [&_input::placeholder]:text-vui-fg-tertiary",
  queueMeta: "flex items-center justify-between gap-2.5 text-[13px] text-[var(--fg-tertiary)]",
  queueBulkZone: "grid min-w-0 max-w-full gap-1.5 overflow-hidden",
  bulkToolbar:
    `grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 px-2 py-1.5 max-[520px]:grid-cols-1 ${reviewRowSurfaceSoft}`,
  bulkCounter:
    "flex min-w-[70px] items-baseline justify-start gap-2 text-xs text-[var(--fg-secondary)] [&_strong]:text-base [&_strong]:text-[var(--fg-primary)]",
  bulkActions: "flex min-w-0 flex-wrap items-center justify-end gap-1.5 max-[520px]:justify-start",
  queueList: "flex min-h-0 max-w-full flex-col gap-1.5 overflow-y-auto overflow-x-hidden pr-1 [scrollbar-gutter:stable] max-[980px]:max-h-none",
  queueItem:
    `w-full cursor-pointer px-2.5 py-[9px] text-left text-inherit transition hover:border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] hover:!bg-[var(--vui-surface-row-hover)] ${reviewRowSurface}`,
  queueItemActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,var(--vui-surface-row))]",
  queueItemTop: "flex items-center justify-between gap-2.5",
  queueTitleRow: "flex min-w-0 items-center justify-start gap-2.5 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis",
  queueHeadline: "my-1.5 min-w-0 break-words leading-normal text-[var(--fg-secondary)]",
  signalRow: "flex min-w-0 flex-wrap items-center justify-start gap-2.5",
  signalPill:
    "inline-flex min-h-6 max-w-full min-w-0 items-center justify-center truncate rounded-[var(--radius-control)] bg-vui-control-muted px-2 text-xs font-semibold text-vui-fg-secondary",
  queueFooter: "flex flex-wrap items-center justify-between gap-2.5 text-xs text-[var(--fg-tertiary)]",
  selectionButton:
    "inline-flex h-7 w-7 flex-none items-center justify-center rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted p-0 text-vui-fg-tertiary disabled:cursor-not-allowed disabled:opacity-55",
  selectionButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm-2)]",
  factGrid: "grid grid-cols-4 gap-2 max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  metricGrid: "grid grid-cols-4 gap-2 max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  signalColumns: "grid grid-cols-2 gap-2 max-[980px]:grid-cols-1",
  formGrid: "grid grid-cols-2 gap-2 max-[980px]:grid-cols-1",
  factCard:
    `min-w-0 px-2.5 py-2 ${reviewRowSurfaceSoft} [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-vui-fg-tertiary [&_strong]:block [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:leading-normal`,
  metricCard:
    `min-w-0 px-2.5 py-2 ${reviewRowSurfaceSoft} [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-vui-fg-tertiary [&_strong]:block [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:leading-normal [&_p]:m-0 [&_p]:mt-1 [&_p]:leading-snug [&_p]:text-vui-fg-secondary`,
  signalSection:
    `min-w-0 px-2.5 py-[9px] ${reviewRowSurfaceSoft} [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold [&_ul]:m-0 [&_ul]:pl-[18px] [&_ul]:leading-relaxed [&_ul]:text-vui-fg-secondary`,
  detailSection:
    `min-w-0 px-2.5 py-[9px] ${reviewRowSurfaceSoft} [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold`,
  decisionSection:
    `grid min-w-0 gap-2 border-[color-mix(in_srgb,var(--accent-warm)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_6%,var(--vui-surface-row))] px-2.5 py-[9px] ${reviewRowSurfaceSoft} [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold`,
  transcriptSection:
    `min-w-0 px-2.5 py-[9px] ${reviewRowSurfaceSoft} [&_summary]:cursor-pointer [&_summary]:font-semibold`,
  evidenceList: "flex max-h-[clamp(168px,28vh,280px)] min-h-0 flex-col gap-1.5 overflow-y-auto overflow-x-hidden pr-1 [scrollbar-gutter:stable]",
  transcriptList: "flex max-h-[clamp(220px,36vh,420px)] min-h-0 flex-col gap-1.5 overflow-y-auto overflow-x-hidden pr-1 [scrollbar-gutter:stable]",
  evidenceCard:
    `min-w-0 px-2.5 py-[9px] ${reviewRowSurfaceSoft} [&_p]:m-0 [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:break-words [&_p]:leading-normal`,
  transcriptCard:
    `min-w-0 px-2.5 py-[9px] ${reviewRowSurfaceSoft} [&_p]:m-0 [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:break-words [&_p]:leading-normal`,
  evidenceTop:
    "grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-center gap-2.5 [&_span]:min-w-0 [&_span]:truncate [&_span]:text-right max-[520px]:grid-cols-1 max-[520px]:items-start max-[520px]:[&_span]:text-left",
  formField: reviewFormField,
  textAreaField: reviewTextAreaField,
  actionRow: "flex flex-wrap items-center justify-start gap-2.5",
  detailHeaderActions: "flex min-w-0 flex-wrap items-center justify-end gap-2.5 max-[520px]:justify-start",
  feedbackText: "m-0 text-[var(--accent-warm-2)]",
  errorText: "m-0 text-[var(--accent-warm-2)]",
  hintText: "m-0 leading-normal text-[var(--fg-secondary)]",
  transcriptMeta: "mt-3.5 grid min-w-0 gap-2.5",
  metaRow:
    "grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-start gap-2.5 text-[var(--fg-secondary)] [&_span]:min-w-0 [&_span]:break-all [&_span]:text-right max-[520px]:grid-cols-1 max-[520px]:[&_span]:text-left",
  emptyState:
    "flex min-h-[82px] flex-col justify-center gap-1 rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-[11px] py-[9px] text-[var(--fg-secondary)] [&_h3]:m-0 [&_h3]:text-[var(--fg-primary)]",
  spin: "animate-spin",
} as const;

export default styles;
