const panelSurface = "rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-panel/94 shadow-none";
const rowSurface = "rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row";
const rowSurfaceSoft = "rounded-[var(--radius-control)] border border-vui-border-subtle bg-[color-mix(in_srgb,var(--vui-surface-row)_84%,var(--vui-surface-panel))]";
const controlSurface = "border border-vui-border-subtle bg-vui-control-muted hover:bg-vui-control-muted-hover";

export const selfEvolutionTrackStyles = {
  pageStack: "grid h-full max-h-full min-h-0 min-w-0 max-w-full overflow-hidden overflow-x-hidden rounded-[var(--radius-panel)] bg-vui-surface-panel max-[1180px]:overflow-visible max-[1180px]:overflow-x-hidden",
  trackShell:
    "grid h-full max-h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] overflow-hidden overflow-x-hidden rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-panel p-3 max-[1180px]:h-auto max-[1180px]:overflow-visible max-[1180px]:overflow-x-hidden max-[760px]:p-2",
  trackBody:
    "min-h-0 min-w-0 max-w-full overflow-hidden overflow-x-hidden pt-2 max-[1180px]:overflow-visible max-[1180px]:overflow-x-hidden",
  pageTabsRow:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 border-b border-vui-border-subtle pb-2 max-[1180px]:grid-cols-1 max-[1180px]:items-stretch",
  runActionBar:
    "grid min-h-[42px] min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 px-1 py-0 max-[900px]:grid-cols-1",
  runActionMain: "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5",
  runActionText: "grid min-w-0 gap-1 [&_strong]:overflow-wrap-anywhere [&_strong]:text-[1rem] [&_strong]:leading-tight [&_strong]:text-[var(--fg-primary)] [&>span]:line-clamp-2 [&>span]:text-[var(--vui-font-sm)] [&>span]:leading-normal [&>span]:text-[var(--fg-secondary)]",
  runActionMeta: "flex min-w-0 flex-wrap items-center gap-1.5",
  runActionCluster: "flex flex-wrap items-center justify-end gap-2 max-[900px]:justify-start",
  primaryAction:
    "inline-flex min-h-8 w-fit max-w-full cursor-pointer items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-control-muted))] px-3 text-[var(--vui-font-sm)] font-semibold text-vui-fg-primary disabled:cursor-default disabled:opacity-50",
  dangerAction:
    "inline-flex min-h-8 w-fit max-w-full cursor-pointer items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_9%,var(--vui-control-muted))] px-3 text-[var(--vui-font-sm)] font-semibold text-[var(--state-error)] disabled:cursor-default disabled:opacity-50",
  workspaceLayout:
    "grid h-full max-h-full min-h-0 min-w-0 max-w-full grid-cols-[var(--self-sidebar-width,360px)_10px_minmax(0,1fr)] items-stretch overflow-hidden overflow-x-hidden max-[1180px]:h-auto max-[1180px]:grid-cols-1 max-[1180px]:overflow-visible max-[1180px]:overflow-x-hidden",
  sideColumn: "grid min-w-0 gap-3",
  sideColumnScrollable: "h-full overflow-y-auto pr-1.5 max-[1180px]:h-auto max-[1180px]:overflow-visible",
  paneCollapsed: "overflow-hidden p-0 invisible",
  centerColumn: "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden overflow-x-hidden max-[1180px]:h-auto max-[1180px]:overflow-visible max-[1180px]:overflow-x-hidden",
  conversationShell: "grid h-full max-h-full min-h-[420px] min-w-0 max-w-full overflow-hidden overflow-x-hidden rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-panel max-[1180px]:h-[min(74vh,760px)] max-[1180px]:overflow-hidden max-[1180px]:overflow-x-hidden max-[760px]:h-[min(72vh,720px)] max-[760px]:min-h-[540px]",
  observationEvidenceRail:
    `grid h-full max-h-full min-h-0 content-start gap-3 overflow-auto p-3.5 max-[1180px]:h-auto max-[1180px]:max-h-none ${panelSurface}`,
  observationEventTimeline: `grid gap-2 p-2.5 ${rowSurfaceSoft}`,
  observationEventItem:
    `grid gap-1.5 px-2.5 py-2 ${rowSurfaceSoft} [&_strong]:overflow-wrap-anywhere [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  agentCardList: "grid gap-2",
  agentCard:
    `grid min-w-0 gap-2 p-2.5 ${rowSurfaceSoft}`,
  agentCardActive:
    "border-[color-mix(in_srgb,var(--accent-cool)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))]",
  agentCardMain:
    "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5 text-inherit no-underline",
  agentCardText:
    "grid min-w-0 gap-0.5 [&_strong]:truncate [&_strong]:text-[0.94rem] [&_strong]:text-[var(--fg-primary)] [&_small]:truncate [&_small]:font-mono [&_small]:text-[var(--vui-font-xs)] [&_small]:text-[var(--fg-tertiary)]",
  agentRoleBadge:
    "inline-flex w-fit min-w-0 max-w-full items-center truncate text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)]",
  agentCardActions: "flex flex-wrap items-center justify-end gap-1.5",
  agentCardAction:
    `inline-flex min-h-7 w-fit items-center justify-center gap-1.5 rounded-md px-2 text-[var(--vui-font-xs)] font-semibold text-vui-fg-secondary no-underline hover:text-vui-fg-primary ${controlSurface}`,
  workflowHeader: "flex min-w-0 flex-wrap items-center gap-2.5",
  workflowCardGrid: "inline-flex w-fit min-w-0 max-w-full flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted p-1",
  workflowCard:
    "inline-flex min-h-8 w-fit cursor-pointer items-center justify-center gap-2 rounded-md border border-transparent bg-transparent px-2.5 py-1 text-[var(--vui-font-sm)] font-semibold text-vui-fg-secondary [&_span]:text-inherit [&_strong]:text-[var(--vui-font-xs)] [&_strong]:font-semibold [&_strong]:text-vui-fg-tertiary",
  workflowCardActive:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-surface-row))] text-vui-fg-primary [&_strong]:text-[var(--accent-cool)]",
  workflowStepSummary:
    "m-0 min-w-0 max-w-[min(100%,760px)] overflow-wrap-anywhere text-[var(--vui-font-xs)] leading-normal text-vui-fg-secondary",
  approvalPanel: `grid min-h-0 content-start gap-3 overflow-auto p-3.5 ${panelSurface}`,
  statusPage: "grid h-full min-h-0 overflow-hidden max-[1180px]:h-auto max-[1180px]:overflow-visible",
  panelStack: "grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-4 overflow-hidden",
  sidebarResizer:
    "relative h-full w-2.5 cursor-col-resize rounded-[var(--radius-control)] border-0 bg-transparent p-0 before:absolute before:bottom-[18px] before:left-1 before:top-[18px] before:w-0.5 before:rounded-full before:bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] before:content-[''] max-[1180px]:hidden",
  segmentedTabs: "inline-flex self-center items-center gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-1 max-[1180px]:self-start",
  tabButton: "min-h-8 cursor-pointer rounded-md border-0 bg-transparent px-3 text-[var(--vui-font-sm)] text-[var(--fg-secondary)]",
  tabButtonActive: "bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]",
  modeSwitch: "inline-flex w-fit flex-wrap items-center gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-1",
  modeTab:
    "inline-flex min-h-8 w-fit cursor-pointer items-center justify-center rounded-md border border-transparent px-3 py-1 text-[var(--vui-font-sm)] text-[var(--fg-secondary)]",
  modeTabActive:
    "inline-flex min-h-8 w-fit cursor-pointer items-center justify-center rounded-md border border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] px-3 py-1 text-[var(--vui-font-sm)] font-semibold text-[var(--accent-warm-2)]",
  surface: `${panelSurface} p-3.5 max-[760px]:p-4`,
  loadingShell:
    "grid min-h-[148px] max-h-[180px] content-start self-start overflow-hidden grid-cols-[minmax(240px,300px)_minmax(0,1fr)] gap-2 max-[1180px]:min-h-[172px] max-[1180px]:max-h-[210px] max-[1180px]:grid-cols-1",
  loadingRail: `grid min-h-0 content-start gap-2.5 p-3 ${rowSurfaceSoft}`,
  loadingPanel:
    `grid min-h-0 content-start gap-2 p-3 ${rowSurfaceSoft} [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-secondary`,
  loadingStatGrid:
    "grid grid-cols-3 gap-1.5 [&_span]:grid [&_span]:min-w-0 [&_span]:gap-1 [&_span]:rounded-[7px] [&_span]:border [&_span]:border-[var(--border-hairline)] [&_span]:px-[7px] [&_span]:py-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:font-mono [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  loadingBody: "grid min-h-0 grid-cols-3 gap-2",
  skeletonLineWide: "block h-2 w-[min(100%,620px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  skeletonLine: "block h-2 w-[min(72%,460px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  skeletonLineShort: "block h-2 w-[min(42%,260px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  petCompanionSurface:
    "grid gap-2.5 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_16%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--vui-surface-panel)_94%,var(--vui-surface-base))] p-3.5",
  petCompanionTone_idle: "",
  petCompanionTone_active: "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))]",
  petCompanionTone_paused: "border-[color-mix(in_srgb,var(--accent-warm)_24%,var(--border-soft))]",
  petCompanionTone_caution: "border-[color-mix(in_srgb,var(--state-warning)_28%,var(--border-soft))]",
  petCompanionTone_error: "border-[color-mix(in_srgb,var(--state-warning)_28%,var(--border-soft))]",
  sectionHeader: "flex items-start justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  itemTop: "flex items-center justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  detailRow:
    "flex items-center justify-between gap-3 border-b border-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] pb-2 max-[760px]:flex-col max-[760px]:items-stretch [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:overflow-wrap-anywhere [&_strong]:text-[0.92rem] [&_strong]:text-[var(--fg-primary)]",
  paginationBar: "flex flex-wrap items-center justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  subsurfaceHeader: "flex items-start justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  eyebrow: "m-0 mb-1 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  sectionTitle: "m-0 text-base text-[var(--fg-primary)]",
  subsurfaceTitle: "m-0 text-[0.98rem] text-[var(--fg-primary)]",
  subsectionTitle: "m-0 text-[var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)]",
  sectionSummary: "m-0 leading-normal text-[var(--fg-secondary)]",
  mutedText: "m-0 leading-normal text-[var(--fg-secondary)]",
  noticeText: "m-0 leading-normal text-[var(--fg-secondary)]",
  feedbackText: "m-0 overflow-wrap-anywhere leading-normal text-[var(--accent-warm-2)]",
  errorText: "m-0 overflow-wrap-anywhere leading-normal text-[var(--state-error)]",
  statusIcon: "inline-flex h-8 w-8 flex-none items-center justify-center rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] text-[var(--accent-cool)]",
  statusPill:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] px-2.5 text-[var(--vui-font-xs)] text-[var(--accent-warm-2)] max-[760px]:w-fit",
  secondaryPill:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-subtle bg-vui-control-muted px-2.5 text-[var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:w-fit",
  counter:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-subtle bg-vui-control-muted px-2.5 text-[var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:w-fit",
  conversationActions: "flex flex-wrap justify-end gap-2",
  headerActionCluster: "flex flex-wrap items-center gap-2",
  toolbarActions: "flex flex-wrap items-center gap-2",
  pillRow: "flex flex-wrap items-center gap-2",
  secondaryAction:
    `inline-flex min-h-[38px] w-fit max-w-full cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-control)] px-3.5 text-vui-fg-primary disabled:cursor-default disabled:opacity-50 ${controlSurface}`,
  paginationButton:
    `inline-flex min-h-[38px] min-w-[38px] w-fit max-w-full cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-control)] px-2.5 text-vui-fg-primary disabled:cursor-default disabled:opacity-50 ${controlSurface}`,
  paginationButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_32%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]",
  spinning: "animate-spin",
  noticeStack: "grid gap-2",
  detailStack: "grid gap-2",
  listBlock: "grid gap-2",
  worktreeFiles: "grid gap-2",
  subsection: "mt-1 grid gap-2",
  noticeBanner: `grid gap-2 px-3.5 py-3 ${rowSurfaceSoft}`,
  formField:
    "grid gap-1.5 [&>span]:text-[var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)]",
  textInput: "w-full max-w-[180px]",
  textArea: "w-full",
  worktreeEscalation:
    "flex items-center justify-between gap-3 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] px-3.5 py-3 [&_p]:flex-[1_1_220px]",
  supportGrid: "grid gap-4",
  subsurface:
    `grid min-h-0 content-start gap-3 overflow-auto p-3.5 ${panelSurface}`,
  listItem:
    `grid gap-2 px-[13px] py-3 ${rowSurfaceSoft} [&_strong]:overflow-wrap-anywhere [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  listItemSelected:
    "border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)]",
  petAvatarStage:
    `relative grid min-h-[164px] place-items-center overflow-hidden max-[760px]:min-h-[200px] ${rowSurface}`,
  petAvatarHalo:
    "absolute inset-auto h-[86px] w-32 rounded-[14px] border border-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_7%,transparent)]",
  petAvatarMark: "relative flex animate-bounce items-center justify-center gap-[7px]",
  petAvatarBody:
    "h-[98px] w-[74px] rounded-[48%_48%_42%_42%] border border-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)] bg-[var(--vui-gradient-route-soft)]",
  petAvatarClaw:
    "h-[42px] w-[30px] rounded-[60%_42%_58%_46%] border border-[color-mix(in_srgb,var(--accent-warm)_36%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_18%,var(--vui-surface-row))]",
  petAvatarBadge:
    "absolute bottom-2.5 left-2.5 inline-flex min-h-7 items-center gap-1.5 rounded-full border border-vui-border-subtle bg-vui-control-muted px-2.5 text-[var(--vui-font-xs)] text-vui-fg-secondary",
  petCompanionCopy: "grid gap-1.5 [&_p]:m-0 [&_p]:text-[0.92rem] [&_p]:leading-normal [&_p]:text-[var(--fg-primary)] [&_span]:m-0 [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-normal [&_span]:text-[var(--fg-secondary)]",
  supportColumns: "grid min-h-0 grid-cols-2 gap-4 max-[1180px]:grid-cols-1",
  subsectionGrid: "grid min-h-0 grid-cols-2 gap-4 max-[1180px]:grid-cols-1",
  headerIcon: "flex-none text-[var(--fg-tertiary)]",
  metricStrip: "grid grid-cols-4 gap-3 max-[1180px]:grid-cols-1 max-[760px]:grid-cols-2",
  stripItem:
    `grid min-h-[58px] gap-1 px-2.5 py-[9px] ${rowSurfaceSoft} [&_span]:text-[var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:overflow-wrap-anywhere [&_strong]:text-[0.92rem] [&_strong]:text-vui-fg-primary`,
  compactMetricGrid: "grid grid-cols-2 gap-2 max-[760px]:grid-cols-1",
  observationMetricGrid: "grid grid-cols-3 gap-2 max-[900px]:grid-cols-1",
  historyToolbar: "flex flex-wrap items-center justify-between gap-3",
  transactionFilterBar: "flex flex-wrap gap-2",
  transactionDateFilterBar:
    "flex flex-wrap items-center gap-2 [&>span]:text-[var(--vui-font-xs)] [&>span]:leading-tight [&>span]:text-[var(--fg-tertiary)]",
  transactionVisibleSummary:
    "inline-flex min-h-[30px] items-center whitespace-nowrap font-mono text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  transactionFilterButton:
    `inline-flex min-h-[34px] w-fit max-w-full cursor-pointer items-center gap-2 rounded-[var(--radius-control)] px-2.5 text-vui-fg-secondary ${controlSurface} [&_strong]:min-w-[22px] [&_strong]:text-right [&_strong]:font-mono [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  transactionFilterButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]",
  transactionDetailsToggle:
    "inline-flex min-h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_78%,transparent)] px-[9px] text-[var(--vui-font-xs)] text-[var(--fg-secondary)] aria-expanded:border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] aria-expanded:text-[var(--accent-cool)]",
  transactionDateGroup:
    "grid gap-2 pt-0.5 [&+&]:mt-1 [&+&]:border-t [&+&]:border-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] [&+&]:pt-3",
  transactionDateHeader:
    "flex min-h-[30px] items-center justify-between gap-2.5 px-0.5 max-[760px]:flex-col max-[760px]:items-stretch [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-tertiary)]",
  transactionGroupList: "grid gap-2",
  selectionToggle:
    `inline-flex min-h-8 w-fit max-w-full cursor-pointer items-center gap-2 rounded-[var(--radius-control)] px-3 text-vui-fg-secondary disabled:cursor-default disabled:opacity-50 ${controlSurface}`,
  checkboxRow: "inline-flex items-center gap-2.5 text-[var(--fg-primary)] [&_input]:h-[15px] [&_input]:w-[15px]",
  transactionTitleStack:
    "grid min-w-0 gap-1 [&_span]:overflow-wrap-anywhere [&_span]:font-mono [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-tertiary)]",
  transactionMetaGrid:
    "grid grid-cols-4 gap-1.5 max-[1180px]:grid-cols-2 [&_span]:min-w-0 [&_span]:overflow-wrap-anywhere [&_span]:rounded-[var(--radius-control)] [&_span]:border [&_span]:border-[var(--border-hairline)] [&_span]:bg-[color-mix(in_srgb,var(--vui-surface-row)_72%,transparent)] [&_span]:px-2 [&_span]:py-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-secondary)]",
  transactionGoalPreview: "m-0 overflow-wrap-anywhere text-[var(--vui-font-xs)] leading-normal text-[var(--fg-secondary)]",
  previewText: "m-0 overflow-wrap-anywhere text-[0.92rem] leading-normal text-[var(--fg-primary)]",
  compactPreviewText: "m-0 line-clamp-2 overflow-wrap-anywhere text-[var(--vui-font-xs)] leading-normal text-[var(--fg-secondary)]",
  rawBlock:
    "overflow-auto rounded-[var(--radius-panel)] border border-[var(--border-hairline)] bg-[color-mix(in_srgb,var(--vui-surface-row)_72%,transparent)] p-3 font-mono text-[var(--vui-font-xs)] leading-relaxed text-[var(--fg-secondary)]",
  transactionDetailsPanel:
    `grid grid-cols-2 gap-2 p-[9px] max-[1180px]:grid-cols-1 ${rowSurfaceSoft}`,
  transactionDetailRow:
    "grid min-w-0 gap-1 [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:overflow-wrap-anywhere [&_strong]:text-[var(--vui-font-xs)] [&_strong]:leading-snug [&_strong]:text-[var(--fg-secondary)]",
  vitalList: "grid gap-2",
  vitalItem: "grid gap-1.5",
  vitalTrack: "h-2 w-full overflow-hidden rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--fg-secondary)_70%,transparent)]",
  vitalFill: "h-full w-[var(--self-vital-progress)] rounded-[var(--radius-control)] bg-[var(--vui-gradient-route-soft)]",
  paginationGroup: "flex flex-wrap items-center gap-2",
  emptyState: "flex min-h-[120px] items-center justify-center text-center text-[var(--fg-secondary)]",
} as const;
