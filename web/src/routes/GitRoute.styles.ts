export const gitRouteStyles: Record<string, string> = {
  route:
    "grid h-full min-h-0 grid-rows-[auto_auto_auto_minmax(0,1fr)] bg-[color-mix(in_srgb,var(--surface-page)_94%,var(--bg-canvas))] max-[860px]:overflow-auto",
  header:
    "mx-2.5 mt-2 min-w-0 border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]",
  panelEyebrow: "m-0 mb-0.5 text-[0.72rem] uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  refreshButton:
    "inline-flex h-[var(--vui-control-height-sm)] min-h-8 w-[var(--vui-control-height-sm)] flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--surface-card)] p-0 text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  summaryGrid: "grid grid-cols-4 gap-[var(--route-summary-gap)] px-3 pt-2 max-[860px]:grid-cols-1",
  summaryCard:
    "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-[var(--route-summary-padding)] text-left text-inherit disabled:cursor-default disabled:opacity-75 [&[data-vui]]:cursor-pointer [&[data-vui]:hover:not(:disabled)]:border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] [&[data-vui]:hover:not(:disabled)]:bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--surface-panel))] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_span]:whitespace-nowrap [&_span]:text-[0.68rem] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.86rem] [&_strong]:text-[var(--fg-primary)]",
  notice:
    "mx-3.5 mt-2 rounded-lg border border-[color-mix(in_srgb,var(--state-error)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_12%,transparent)] px-2.5 py-2 text-[0.86rem] text-[var(--state-error)]",
  workspace:
    "grid min-h-0 grid-cols-[var(--git-change-panel-width,330px)_10px_minmax(520px,1fr)_minmax(270px,330px)] p-[var(--route-workspace-padding)] max-[1200px]:grid-cols-[minmax(280px,var(--git-change-panel-width,320px))_8px_minmax(420px,1fr)] max-[1200px]:grid-rows-[minmax(0,1fr)_minmax(210px,34vh)] max-[1200px]:gap-y-2 max-[860px]:grid-cols-1 max-[860px]:grid-rows-none max-[860px]:gap-3.5",
  workspaceOverview:
    "grid-cols-[minmax(340px,0.9fr)_minmax(500px,1.18fr)_minmax(270px,0.62fr)] gap-2 max-[1200px]:grid-cols-[minmax(0,1fr)_minmax(280px,340px)] max-[1200px]:grid-rows-[minmax(260px,0.92fr)_minmax(240px,0.8fr)] max-[860px]:grid-cols-1 max-[860px]:grid-rows-none",
  resizeHandle:
    "relative min-w-2.5 cursor-col-resize touch-none border-0 bg-transparent p-0 outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-[3px] before:-translate-x-1/2 before:rounded-full before:bg-[color-mix(in_srgb,var(--surface-card)_8%,transparent)] before:transition before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:before:shadow-[var(--vui-shadow-soft)] focus-visible:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] focus-visible:before:shadow-[var(--vui-shadow-soft)] max-[860px]:hidden",
  changePanel:
    "grid min-h-0 grid-rows-[auto_auto_auto_minmax(0,1fr)] gap-[9px] rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-2.5",
  commitPanel:
    "grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-[9px] rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-2.5 max-[1200px]:col-span-full max-[1200px]:row-start-2 max-[1200px]:grid-cols-[minmax(320px,0.9fr)_minmax(280px,1.1fr)] max-[1200px]:grid-rows-[auto_minmax(0,1fr)] max-[1200px]:items-start max-[860px]:col-auto max-[860px]:row-auto max-[860px]:grid-cols-1 max-[860px]:grid-rows-[auto_auto_minmax(180px,1fr)]",
  gitOverviewPanel:
    "grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 max-[1200px]:[.workspaceOverview_&]:col-start-1 max-[1200px]:[.workspaceOverview_&]:row-start-1 max-[860px]:[.workspaceOverview_&]:col-auto max-[860px]:[.workspaceOverview_&]:row-auto",
  cleanStateStrip:
    "grid w-full min-w-0 cursor-pointer grid-cols-[minmax(170px,auto)_minmax(0,1fr)] items-center gap-3 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] px-3 py-2.5 text-left text-inherit hover:border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--surface-panel))] max-[860px]:grid-cols-1 [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_h2]:m-0 [&_h2]:text-[0.98rem] [&_h2]:text-[var(--fg-primary)] [&>span]:min-w-0 [&>span]:overflow-hidden [&>span]:text-ellipsis [&>span]:whitespace-nowrap [&>span]:text-[0.8rem] [&>span]:leading-tight [&>span]:text-[var(--fg-secondary)]",
  gitSituationGrid: "grid min-h-0 min-w-0 grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] gap-2 max-[860px]:grid-cols-1",
  gitSituationCard:
    "grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-2.5 [&_h2]:m-0 [&_h2]:text-[0.98rem] [&_h2]:text-[var(--fg-primary)]",
  situationList: "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  worktreeList: "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  worktreeItem:
    "grid w-full min-w-0 cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-muted)] px-[9px] py-2 text-left text-inherit hover:border-[color-mix(in_srgb,var(--accent-cool)_32%,transparent)] hover:bg-[var(--surface-panel-strong)] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_div]:grid [&_div]:min-w-0 [&_div]:gap-1 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.8rem] [&_strong]:text-[var(--fg-primary)] [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[0.72rem] [&_span]:text-[var(--fg-tertiary)] [&_code]:whitespace-nowrap [&_code]:font-mono [&_code]:text-[0.75rem] [&_code]:text-[var(--accent-warm-2)]",
  historyPanel:
    "grid-rows-[auto_minmax(0,1fr)] max-[1200px]:[.workspaceOverview_&]:col-start-2 max-[1200px]:[.workspaceOverview_&]:row-[1/span_2] max-[1200px]:[.workspaceOverview_&]:grid-cols-1 max-[1200px]:[.workspaceOverview_&]:grid-rows-[auto_minmax(0,1fr)] max-[860px]:[.workspaceOverview_&]:col-auto max-[860px]:[.workspaceOverview_&]:row-auto",
  paneCollapsed: "overflow-hidden p-0 invisible",
  panelHeader: "flex items-center justify-between gap-2 [&_h2]:m-0 [&_h2]:text-[0.94rem]",
  countPill:
    "inline-flex min-h-6 items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-2 text-[0.74rem] text-[var(--accent-cool)]",
  inlineMeta:
    "inline-flex min-h-6 items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-2 text-[0.74rem] text-[var(--accent-cool)]",
  filterRow: "flex flex-wrap gap-1.5",
  selectionRow: "flex gap-1.5",
  filterButton:
    "inline-flex min-h-7 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--surface-card)] px-2 py-1 text-[0.74rem] text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-[var(--fg-primary)]",
  filterButtonActive:
    "inline-flex min-h-7 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] px-2 py-1 text-[0.74rem] text-[var(--accent-warm-2)]",
  selectionButton:
    "inline-flex min-h-7 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--surface-card)] px-2 py-1 text-[0.74rem] text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  fileList: "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  commitList: "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  fileButton:
    "grid w-full grid-cols-[24px_38px_minmax(0,1fr)] items-start gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-muted)] p-2 text-left text-[var(--fg-primary)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-strong)]",
  fileButtonActive:
    "grid w-full grid-cols-[24px_38px_minmax(0,1fr)] items-start gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[var(--surface-active-neutral)] p-2 text-left text-[var(--fg-primary)] shadow-[var(--vui-shadow-inset-accent)]",
  fileButtonSelected:
    "border-[color-mix(in_srgb,var(--state-success)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_8%,var(--surface-panel-muted))]",
  fileStatus: "font-mono text-[0.76rem] text-[var(--accent-warm-2)]",
  fileCheckButton:
    "inline-grid h-5 min-h-5 w-5 min-w-5 place-items-center border-0 bg-transparent p-0 text-left text-[var(--accent-warm-2)]",
  fileCopyButton:
    "grid min-w-0 gap-1 border-0 bg-transparent p-0 text-left text-inherit [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_strong]:block [&_strong]:min-w-0 [&_strong]:max-w-full [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap",
  filePathText: "m-0 overflow-hidden text-ellipsis whitespace-nowrap text-[0.78rem] leading-tight text-[var(--fg-secondary)]",
  fileBadgeRow: "flex min-h-5 flex-wrap gap-[5px]",
  fileBadgeActive:
    "inline-flex min-h-[19px] items-center rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] px-1.5 text-[0.68rem] leading-none text-[var(--accent-warm-2)]",
  fileBadgeSelected:
    "inline-flex min-h-[19px] items-center rounded-full border border-[color-mix(in_srgb,var(--state-success)_28%,transparent)] px-1.5 text-[0.68rem] leading-none text-[var(--state-success)]",
  diffPanel: "min-h-0 min-w-0",
  objectDetailPanel:
    "min-h-0 min-w-0 max-[1200px]:[.workspaceOverview_&]:col-start-1 max-[1200px]:[.workspaceOverview_&]:row-start-2 max-[860px]:[.workspaceOverview_&]:col-auto max-[860px]:[.workspaceOverview_&]:row-auto",
  emptyPreview:
    "grid h-full content-start justify-items-start gap-[7px] rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-3.5 text-[var(--fg-secondary)] [&_p]:m-0 [&_p]:text-[0.78rem] [&_p]:leading-tight [&_p]:text-[var(--fg-secondary)] [&_strong]:text-[0.98rem] [&_strong]:text-[var(--fg-primary)] [&_svg]:h-[18px] [&_svg]:w-[18px] [&_svg]:text-[var(--accent-cool)]",
  emptyState: "m-0 text-[0.78rem] leading-tight text-[var(--fg-secondary)]",
  commitItem:
    "grid w-full min-w-0 cursor-pointer gap-1.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-muted)] p-[9px] text-left text-inherit hover:border-[color-mix(in_srgb,var(--accent-cool)_32%,transparent)] hover:bg-[var(--surface-panel-strong)] [&_[data-slot=vui-button-content]]:grid [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-content]]:gap-1.5 [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:gap-1.5 [&_strong]:block [&_strong]:min-w-0 [&_strong]:max-w-full [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_p]:m-0 [&_p]:text-[0.78rem] [&_p]:leading-tight [&_p]:text-[var(--fg-secondary)]",
  objectItemActive:
    "border-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--surface-panel-muted))] shadow-[var(--vui-shadow-inset-accent)]",
  manualCommitPanel:
    "grid min-h-0 max-h-[min(100%,calc(100dvh-190px))] content-start gap-[9px] overflow-auto border-b border-[var(--border-soft)] pb-2.5 max-[1200px]:row-span-2 max-[1200px]:border-b-0 max-[1200px]:border-r max-[1200px]:pb-0 max-[1200px]:pr-3.5 max-[860px]:row-auto max-[860px]:max-h-none max-[860px]:overflow-visible max-[860px]:border-b max-[860px]:border-r-0 max-[860px]:pb-3.5 max-[860px]:pr-0",
  commitScopeBox: "grid gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-muted)] p-[9px]",
  scopeHeader:
    "flex items-start justify-between gap-2.5 [&_div]:grid [&_div]:min-w-0 [&_div]:gap-1 [&_div>span]:m-0 [&_div>span]:text-[0.76rem] [&_div>span]:leading-snug [&_div>span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.9rem] [&_strong]:text-[var(--fg-primary)]",
  scopeReady:
    "inline-flex min-h-[23px] items-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--state-success)_26%,transparent)] px-2 text-[var(--state-success)]",
  scopeList: "grid gap-1.5",
  scopeItem:
    "grid min-w-0 grid-cols-[42px_minmax(0,1fr)] items-center gap-2 [&_span]:font-mono [&_span]:text-[0.72rem] [&_span]:text-[var(--accent-warm-2)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.76rem] [&_strong]:font-medium [&_strong]:text-[var(--fg-secondary)]",
  scopeEmpty: "m-0 text-[0.76rem] leading-snug text-[var(--fg-tertiary)]",
  scopeMore: "m-0 text-[0.76rem] leading-snug text-[var(--fg-tertiary)]",
  scopeWarning:
    "grid gap-1 rounded-lg border border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] p-[9px] [&_p]:m-0 [&_p]:text-[0.76rem] [&_p]:leading-snug [&_p]:text-[var(--fg-tertiary)] [&_span]:m-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[0.76rem] [&_span]:leading-snug [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-[0.78rem] [&_strong]:text-[var(--state-warning)]",
  messageField:
    "grid gap-[7px] [&_span]:text-[0.78rem] [&_span]:text-[var(--fg-tertiary)] [&_select]:min-h-[34px] [&_select]:w-full [&_select]:rounded-lg [&_select]:border [&_select]:border-[var(--border-soft)] [&_select]:bg-[var(--surface-input-strong)] [&_select]:px-[9px] [&_select]:py-2 [&_select]:leading-snug [&_select]:text-[var(--fg-primary)] [&_select:focus]:border-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)] [&_select:focus]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-lg [&_textarea]:border [&_textarea]:border-[var(--border-soft)] [&_textarea]:bg-[var(--surface-input-strong)] [&_textarea]:px-[9px] [&_textarea]:py-2 [&_textarea]:leading-snug [&_textarea]:text-[var(--fg-primary)] [&_textarea:focus]:border-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)] [&_textarea:focus]:outline-none",
  promptTemplateField: "[&_textarea]:min-h-[86px] [&_textarea]:font-mono [&_textarea]:text-[0.76rem]",
  modelDefaultRow:
    "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[0.76rem] [&_span]:text-[var(--fg-tertiary)]",
  modelActionRow: "grid-cols-[auto] justify-end",
  commitActions:
    "grid min-w-0 grid-cols-[repeat(2,max-content)] justify-end gap-2 [&_.secondaryButton]:w-fit [&_.primaryButton]:w-fit",
  secondaryButton:
    "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--surface-card)] px-[9px] py-1.5 text-[0.8rem] text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  primaryButton:
    "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] px-[9px] py-1.5 text-[0.8rem] text-[var(--accent-warm-2)] hover:border-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-warm)_22%,transparent)] disabled:cursor-default disabled:opacity-55",
  commitNotice: "m-0 text-[0.78rem] leading-snug text-[var(--state-success)]",
  commitNoticeError: "m-0 text-[0.78rem] leading-snug text-[var(--state-error)]",
  commitBlockReason: "m-0 text-[0.78rem] leading-snug text-[var(--accent-warm-2)]",
  commitReady: "m-0 text-[0.78rem] leading-snug text-[var(--state-success)]",
  commitHeader:
    "flex min-w-0 items-center justify-between gap-2 [&_code]:min-w-0 [&_code]:text-[0.78rem] [&_code]:text-[var(--accent-warm-2)] [&_span]:inline-flex [&_span]:min-w-0 [&_span]:items-center [&_span]:gap-[5px] [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:text-[0.76rem] [&_span]:text-[var(--fg-tertiary)]",
};
