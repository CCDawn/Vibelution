const styles = {
  page:
    "flex h-full min-h-0 flex-col gap-1.5 overflow-hidden px-3 py-2 pb-3 text-[var(--fg-primary)] max-[980px]:overflow-auto max-[980px]:pb-[18px]",
  toolbar: "flex min-w-0 flex-wrap items-center justify-between gap-[var(--route-topbar-gap)]",
  toolbarIntro: "grid min-w-[260px] max-w-[760px] gap-0.5",
  toolbarControls: "flex flex-wrap items-center justify-end gap-3",
  eyebrow: "m-0 mb-0.5 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--accent-warm-2)]",
  title: "m-0 whitespace-nowrap text-[length:var(--route-topbar-title-size)] leading-[1.08]",
  subtitle:
    "m-0 max-w-none overflow-hidden text-ellipsis whitespace-nowrap text-[length:var(--route-topbar-subtitle-size)] leading-tight text-[var(--fg-secondary)]",
  summaryStrip: "grid grid-cols-5 gap-[var(--route-summary-gap)] max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  summaryCard:
    "grid min-h-7 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-1.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2 py-1 [&_span]:whitespace-nowrap [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)]",
  lifecyclePanel:
    "flex min-h-[34px] items-center justify-between gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2 py-1.5 max-[980px]:flex-col max-[980px]:items-start",
  lifecyclePills: "flex flex-wrap justify-end gap-2 max-[980px]:justify-start",
  workspace:
    "grid min-h-0 flex-1 grid-cols-[var(--review-queue-width,380px)_12px_minmax(0,1fr)] overflow-hidden max-[980px]:grid-cols-1 max-[980px]:gap-y-3 max-[980px]:overflow-visible",
  resizeHandle:
    "relative min-w-3 cursor-col-resize touch-none border-0 bg-transparent p-0 outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-[3px] before:-translate-x-1/2 before:rounded-[var(--radius-control)] before:bg-[var(--surface-resize-track)] before:transition before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:before:shadow-[var(--vui-shadow-soft)] focus-visible:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] focus-visible:before:shadow-[var(--vui-shadow-soft)] max-[980px]:hidden",
  queuePanel:
    "flex min-h-0 flex-col gap-2 overflow-hidden rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] p-[9px] max-[980px]:max-h-none max-[980px]:overflow-visible",
  paneCollapsed: "overflow-hidden p-0 invisible",
  detailPanel:
    "flex min-h-0 flex-col gap-2.5 overflow-auto rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] p-[9px] max-[980px]:overflow-visible",
  panelHeader: "flex items-start justify-between gap-3.5",
  detailHeader: "flex items-start justify-between gap-3.5",
  sectionHeader: "flex items-start justify-between gap-3.5",
  sectionTitle: "m-0 text-base font-bold leading-snug",
  detailTitle: "m-0 text-base font-bold leading-snug",
  detailLead: "m-0 mt-1.5 leading-snug text-[var(--fg-secondary)]",
  secondaryPill:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2 text-xs font-semibold text-[var(--fg-secondary)]",
  statusBadge:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-transparent px-2 text-xs font-semibold",
  statusPending:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusPositive:
    "border-[color-mix(in_srgb,var(--state-success)_20%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusNegative:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusDiscard:
    "border-[color-mix(in_srgb,var(--surface-card)_18%,transparent)] bg-[color-mix(in_srgb,var(--surface-card)_12%,transparent)] text-[var(--fg-secondary)]",
  queueControls: "flex flex-col gap-2.5",
  filterSegmented: "flex flex-wrap items-center gap-1.5",
  decisionSegmented: "flex flex-wrap items-center gap-1.5",
  filterButton:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[13px] font-semibold text-[var(--fg-primary)] no-underline transition hover:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] disabled:cursor-not-allowed disabled:opacity-55",
  decisionButton:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[13px] font-semibold text-[var(--fg-primary)] no-underline transition hover:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] disabled:cursor-not-allowed disabled:opacity-55",
  filterButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]",
  decisionButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]",
  primaryAction:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] px-2.5 text-[13px] font-semibold text-[var(--accent-warm-2)] no-underline transition disabled:cursor-not-allowed disabled:opacity-55",
  secondaryAction:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[13px] font-semibold text-[var(--fg-primary)] no-underline transition hover:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)]",
  compactAction:
    "inline-flex min-h-7 min-w-0 items-center justify-center gap-1.5 overflow-hidden whitespace-nowrap rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2 text-[11px] font-semibold text-[var(--fg-primary)] no-underline transition disabled:cursor-not-allowed disabled:opacity-55 [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-label]]:truncate",
  dangerAction:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_22%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] text-[var(--accent-warm-2)]",
  searchField:
    "flex min-h-[34px] items-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[var(--fg-secondary)] [&_input]:w-full [&_input]:border-0 [&_input]:bg-transparent [&_input]:font-[inherit] [&_input]:text-[var(--fg-primary)] [&_input]:outline-none [&_input::placeholder]:text-[var(--fg-tertiary)]",
  queueMeta: "flex items-center justify-between gap-2.5 text-[13px] text-[var(--fg-tertiary)]",
  bulkToolbar:
    "grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2 rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2 py-1.5",
  bulkCounter:
    "flex min-w-[70px] items-baseline justify-start gap-2 text-xs text-[var(--fg-secondary)] [&_strong]:text-base [&_strong]:text-[var(--fg-primary)]",
  bulkActions: "grid min-w-0 grid-cols-3 gap-1.5",
  queueList: "flex min-h-0 flex-col gap-1.5 overflow-auto pr-1 max-[980px]:max-h-[420px]",
  queueItem:
    "w-full cursor-pointer rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] px-2.5 py-[9px] text-left text-inherit transition hover:border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] hover:bg-[var(--surface-panel-strong)]",
  queueItemActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] bg-[var(--surface-panel-strong)]",
  queueItemTop: "flex items-center justify-between gap-2.5",
  queueTitleRow: "flex min-w-0 items-center justify-start gap-2.5 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis",
  queueHeadline: "my-1.5 leading-normal text-[var(--fg-secondary)]",
  signalRow: "flex flex-wrap items-center justify-start gap-2.5",
  signalPill:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] bg-[var(--surface-card-hover)] px-2 text-xs font-semibold text-[var(--fg-secondary)]",
  queueFooter: "flex items-center justify-between gap-2.5 text-xs text-[var(--fg-tertiary)]",
  selectionButton:
    "inline-flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] p-0 text-[var(--fg-tertiary)] disabled:cursor-not-allowed disabled:opacity-55",
  selectionButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm-2)]",
  factGrid: "grid grid-cols-4 gap-2 max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  metricGrid: "grid grid-cols-4 gap-2 max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  signalColumns: "grid grid-cols-2 gap-2 max-[980px]:grid-cols-1",
  formGrid: "grid grid-cols-2 gap-2 max-[980px]:grid-cols-1",
  factCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2.5 py-2 [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:block [&_strong]:leading-normal",
  metricCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2.5 py-2 [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:block [&_strong]:leading-normal [&_p]:m-0 [&_p]:mt-1 [&_p]:leading-snug [&_p]:text-[var(--fg-secondary)]",
  signalSection:
    "rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2.5 py-[9px] [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold [&_ul]:m-0 [&_ul]:pl-[18px] [&_ul]:leading-relaxed [&_ul]:text-[var(--fg-secondary)]",
  detailSection:
    "rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2.5 py-[9px] [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold",
  transcriptSection:
    "rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2.5 py-[9px] [&_summary]:cursor-pointer [&_summary]:font-semibold",
  evidenceList: "flex flex-col gap-1.5",
  transcriptList: "flex flex-col gap-1.5",
  evidenceCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] px-2.5 py-[9px] [&_p]:m-0 [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:leading-normal",
  transcriptCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] px-2.5 py-[9px] [&_p]:m-0 [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:leading-normal",
  evidenceTop: "flex items-center justify-between gap-2.5",
  formField:
    "block [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_input]:min-h-[34px] [&_input]:w-full [&_input]:rounded-lg [&_input]:border [&_input]:border-[var(--border-soft)] [&_input]:bg-[var(--surface-card-muted)] [&_input]:px-3 [&_input]:font-[inherit] [&_input]:text-[var(--fg-primary)] [&_input]:outline-none [&_input::placeholder]:text-[var(--fg-tertiary)] [&_select]:min-h-[34px] [&_select]:w-full [&_select]:rounded-lg [&_select]:border [&_select]:border-[var(--border-soft)] [&_select]:bg-[var(--surface-card-muted)] [&_select]:px-3 [&_select]:font-[inherit] [&_select]:text-[var(--fg-primary)] [&_select]:outline-none",
  textAreaField:
    "block [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_textarea]:min-h-[84px] [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-lg [&_textarea]:border [&_textarea]:border-[var(--border-soft)] [&_textarea]:bg-[var(--surface-card-muted)] [&_textarea]:p-2.5 [&_textarea]:font-[inherit] [&_textarea]:text-[var(--fg-primary)] [&_textarea]:outline-none [&_textarea::placeholder]:text-[var(--fg-tertiary)]",
  actionRow: "flex items-center justify-between gap-2.5",
  detailHeaderActions: "flex items-center justify-between gap-2.5",
  feedbackText: "m-0 text-[var(--accent-warm-2)]",
  errorText: "m-0 text-[var(--accent-warm-2)]",
  hintText: "m-0 leading-normal text-[var(--fg-secondary)]",
  transcriptMeta: "mt-3.5 grid gap-2.5",
  metaRow:
    "flex items-start justify-between gap-4 text-[var(--fg-secondary)] [&_span]:flex-1 [&_span]:break-all [&_span]:text-right",
  emptyState:
    "flex min-h-[82px] flex-col justify-center gap-1 rounded-lg border border-dashed border-[var(--border-strong)] px-[11px] py-[9px] text-[var(--fg-secondary)] [&_h3]:m-0 [&_h3]:text-[var(--fg-primary)]",
  spin: "animate-spin",
} as const;

export default styles;
