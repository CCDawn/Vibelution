export const selfEvolutionTrackStyles: Record<string, string> = {
  pageStack: "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2.5 overflow-hidden max-[1180px]:overflow-visible",
  pageTabsRow: "flex justify-end",
  workspaceLayout:
    "grid h-full min-h-0 grid-cols-[var(--self-sidebar-width,304px)_10px_minmax(0,1fr)] items-stretch overflow-hidden max-[1180px]:h-auto max-[1180px]:grid-cols-1 max-[1180px]:overflow-visible",
  sideColumn: "grid min-w-0 gap-3",
  sideColumnScrollable: "h-full overflow-y-auto pr-1.5 max-[1180px]:h-auto max-[1180px]:overflow-visible",
  paneCollapsed: "overflow-hidden p-0 invisible",
  centerColumn: "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2.5 overflow-hidden max-[1180px]:h-auto max-[1180px]:overflow-visible",
  conversationShell: "grid h-full min-h-0 overflow-hidden max-[1180px]:h-auto max-[1180px]:overflow-visible max-[760px]:h-[min(72vh,720px)] max-[760px]:min-h-[540px]",
  workflowCardGrid: "grid grid-cols-2 gap-2 max-[760px]:grid-cols-1",
  workflowCard:
    "grid min-h-[88px] cursor-pointer content-start gap-1.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] p-3 text-left text-[var(--fg-secondary)] [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_strong]:text-[0.95rem] [&_strong]:text-[var(--fg-primary)] [&_small]:line-clamp-2 [&_small]:text-[var(--vui-font-xs)] [&_small]:leading-normal",
  workflowCardActive:
    "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--surface-card))]",
  approvalPanel: "grid min-h-0 content-start gap-3 overflow-auto rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] p-3.5",
  statusPage: "grid h-full min-h-0 overflow-hidden max-[1180px]:h-auto max-[1180px]:overflow-visible",
  panelStack: "grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-4 overflow-hidden",
  sidebarResizer:
    "relative h-full w-2.5 cursor-col-resize rounded-[var(--radius-control)] border-0 bg-transparent p-0 before:absolute before:bottom-[18px] before:left-1 before:top-[18px] before:w-0.5 before:rounded-full before:bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] before:content-[''] max-[1180px]:hidden",
  segmentedTabs: "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] p-1",
  tabButton: "min-h-9 cursor-pointer rounded-md border-0 bg-transparent px-4 text-[var(--fg-secondary)]",
  tabButtonActive: "bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]",
  modeSwitch: "inline-flex w-fit flex-wrap items-center gap-1 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] p-1",
  modeTab:
    "inline-flex min-h-8 w-fit cursor-pointer items-center justify-center rounded-md border border-transparent px-3 py-1 text-[var(--vui-font-sm)] text-[var(--fg-secondary)]",
  modeTabActive:
    "inline-flex min-h-8 w-fit cursor-pointer items-center justify-center rounded-md border border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] px-3 py-1 text-[var(--vui-font-sm)] font-semibold text-[var(--accent-warm-2)]",
  surface: "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-3.5 max-[760px]:p-4",
  observationPanel:
    "grid min-h-0 content-start gap-3 overflow-auto rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] p-3.5",
  loadingShell:
    "grid min-h-[148px] max-h-[180px] content-start self-start overflow-hidden grid-cols-[minmax(240px,300px)_minmax(0,1fr)] gap-2 max-[1180px]:min-h-[172px] max-[1180px]:max-h-[210px] max-[1180px]:grid-cols-1",
  loadingRail: "grid min-h-0 content-start gap-2.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] p-3",
  loadingPanel:
    "grid min-h-0 content-start gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] p-3 [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-secondary)]",
  loadingStatGrid:
    "grid grid-cols-3 gap-1.5 [&_span]:grid [&_span]:min-w-0 [&_span]:gap-1 [&_span]:rounded-[7px] [&_span]:border [&_span]:border-[var(--border-hairline)] [&_span]:px-[7px] [&_span]:py-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:font-mono [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  loadingBody: "grid min-h-0 grid-cols-3 gap-2",
  skeletonLineWide: "block h-2 w-[min(100%,620px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  skeletonLine: "block h-2 w-[min(72%,460px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  skeletonLineShort: "block h-2 w-[min(42%,260px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  petCompanionSurface:
    "grid gap-3 rounded-lg border border-[color-mix(in_srgb,var(--accent-cool)_16%,var(--border-soft))] bg-[var(--surface-panel)] p-3.5",
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
  statusIcon: "inline-flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] text-[var(--accent-cool)]",
  statusPill:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] px-2.5 text-[var(--vui-font-xs)] text-[var(--accent-warm-2)] max-[760px]:w-fit",
  secondaryPill:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[var(--surface-panel-strong)] px-2.5 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] max-[760px]:w-fit",
  counter:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[var(--surface-panel-strong)] px-2.5 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] max-[760px]:w-fit",
  conversationActions: "flex flex-wrap justify-end gap-2",
  headerActionCluster: "flex flex-wrap items-center gap-2",
  toolbarActions: "flex flex-wrap items-center gap-2",
  pillRow: "flex flex-wrap items-center gap-2",
  secondaryAction:
    "inline-flex min-h-[38px] cursor-pointer items-center justify-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_20%,transparent)] bg-[var(--surface-panel-strong)] px-3.5 text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-50",
  paginationButton:
    "inline-flex min-h-[38px] min-w-[38px] cursor-pointer items-center justify-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_20%,transparent)] bg-[var(--surface-panel-strong)] px-2.5 text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-50",
  paginationButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_32%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]",
  spinning: "animate-spin",
  noticeStack: "grid gap-2",
  detailStack: "grid gap-2",
  listBlock: "grid gap-2",
  worktreeFiles: "grid gap-2",
  subsection: "mt-1 grid gap-2",
  noticeBanner: "grid gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] px-3.5 py-3",
  formField:
    "grid gap-1.5 [&>span]:text-[var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)]",
  textInput: "w-full max-w-[180px]",
  textArea: "w-full",
  worktreeEscalation:
    "flex items-center justify-between gap-3 rounded-lg border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--surface-card))] px-3.5 py-3 [&_p]:flex-[1_1_220px]",
  supportGrid: "grid gap-4",
  subsurface:
    "grid min-h-0 content-start gap-3 overflow-auto rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] p-3.5",
  listItem:
    "grid gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] px-[13px] py-3 [&_strong]:overflow-wrap-anywhere [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  listItemSelected:
    "border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)]",
  petAvatarStage:
    "relative grid min-h-[164px] place-items-center overflow-hidden rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] max-[760px]:min-h-[200px]",
  petAvatarHalo:
    "absolute inset-auto h-[86px] w-32 rounded-[14px] border border-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_7%,transparent)]",
  petAvatarMark: "relative flex animate-bounce items-center justify-center gap-[7px]",
  petAvatarBody:
    "h-[98px] w-[74px] rounded-[48%_48%_42%_42%] border border-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)] bg-[var(--vui-gradient-route-soft)]",
  petAvatarClaw:
    "h-[42px] w-[30px] rounded-[60%_42%_58%_46%] border border-[color-mix(in_srgb,var(--accent-warm)_36%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_18%,var(--surface-panel-strong))]",
  petAvatarBadge:
    "absolute bottom-2.5 left-2.5 inline-flex min-h-7 items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[var(--surface-panel-strong)] px-2.5 text-[var(--vui-font-xs)] text-[var(--fg-secondary)]",
  petCompanionCopy: "grid gap-1.5 [&_p]:m-0 [&_p]:text-[0.92rem] [&_p]:leading-normal [&_p]:text-[var(--fg-primary)] [&_span]:m-0 [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-normal [&_span]:text-[var(--fg-secondary)]",
  supportColumns: "grid min-h-0 grid-cols-2 gap-4 max-[1180px]:grid-cols-1",
  subsectionGrid: "grid min-h-0 grid-cols-2 gap-4 max-[1180px]:grid-cols-1",
  headerIcon: "flex-none text-[var(--fg-tertiary)]",
  metricStrip: "grid grid-cols-4 gap-3 max-[1180px]:grid-cols-1 max-[760px]:grid-cols-2",
  stripItem:
    "grid min-h-[58px] gap-1 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] px-2.5 py-[9px] [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:overflow-wrap-anywhere [&_strong]:text-[0.92rem] [&_strong]:text-[var(--fg-primary)]",
  compactMetricGrid: "grid grid-cols-2 gap-2 max-[760px]:grid-cols-1",
  observationMetricGrid: "grid grid-cols-3 gap-2 max-[900px]:grid-cols-1",
  historyToolbar: "flex flex-wrap items-center justify-between gap-3",
  transactionFilterBar: "flex flex-wrap gap-2",
  transactionDateFilterBar:
    "flex flex-wrap items-center gap-2 [&>span]:text-[var(--vui-font-xs)] [&>span]:leading-tight [&>span]:text-[var(--fg-tertiary)]",
  transactionVisibleSummary:
    "inline-flex min-h-[30px] items-center whitespace-nowrap font-mono text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  transactionFilterButton:
    "inline-flex min-h-[34px] cursor-pointer items-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[var(--surface-panel-strong)] px-2.5 text-[var(--fg-secondary)] [&_strong]:min-w-[22px] [&_strong]:text-right [&_strong]:font-mono [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  transactionFilterButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]",
  transactionDetailsToggle:
    "inline-flex min-h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--surface-panel-strong)_78%,transparent)] px-[9px] text-[var(--vui-font-xs)] text-[var(--fg-secondary)] aria-expanded:border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] aria-expanded:text-[var(--accent-cool)]",
  transactionDateGroup:
    "grid gap-2 pt-0.5 [&+&]:mt-1 [&+&]:border-t [&+&]:border-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] [&+&]:pt-3",
  transactionDateHeader:
    "flex min-h-[30px] items-center justify-between gap-2.5 px-0.5 max-[760px]:flex-col max-[760px]:items-stretch [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-tertiary)]",
  transactionGroupList: "grid gap-2",
  selectionToggle:
    "inline-flex min-h-8 cursor-pointer items-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_20%,transparent)] bg-[var(--surface-panel-strong)] px-3 text-[var(--fg-secondary)] disabled:cursor-default disabled:opacity-50",
  checkboxRow: "inline-flex items-center gap-2.5 text-[var(--fg-primary)] [&_input]:h-[15px] [&_input]:w-[15px]",
  transactionTitleStack:
    "grid min-w-0 gap-1 [&_span]:overflow-wrap-anywhere [&_span]:font-mono [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-tertiary)]",
  transactionMetaGrid:
    "grid grid-cols-4 gap-1.5 max-[1180px]:grid-cols-2 [&_span]:min-w-0 [&_span]:overflow-wrap-anywhere [&_span]:rounded-[7px] [&_span]:border [&_span]:border-[var(--border-hairline)] [&_span]:bg-[color-mix(in_srgb,var(--surface-panel-strong)_72%,transparent)] [&_span]:px-2 [&_span]:py-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-secondary)]",
  transactionGoalPreview: "m-0 overflow-wrap-anywhere text-[var(--vui-font-xs)] leading-normal text-[var(--fg-secondary)]",
  previewText: "m-0 overflow-wrap-anywhere text-[0.92rem] leading-normal text-[var(--fg-primary)]",
  rawBlock:
    "overflow-auto rounded-lg border border-[var(--border-hairline)] bg-[color-mix(in_srgb,var(--surface-panel-strong)_72%,transparent)] p-3 font-mono text-[var(--vui-font-xs)] leading-relaxed text-[var(--fg-secondary)]",
  transactionDetailsPanel:
    "grid grid-cols-2 gap-2 rounded-lg border border-[var(--border-hairline)] bg-[color-mix(in_srgb,var(--surface-panel-strong)_54%,transparent)] p-[9px] max-[1180px]:grid-cols-1",
  transactionDetailRow:
    "grid min-w-0 gap-1 [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:overflow-wrap-anywhere [&_strong]:text-[var(--vui-font-xs)] [&_strong]:leading-snug [&_strong]:text-[var(--fg-secondary)]",
  vitalList: "grid gap-2",
  vitalItem: "grid gap-1.5",
  vitalTrack: "h-2 w-full overflow-hidden rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--fg-secondary)_70%,transparent)]",
  vitalFill: "h-full rounded-[var(--radius-control)] bg-[var(--vui-gradient-route-soft)]",
  paginationGroup: "flex flex-wrap items-center gap-2",
  emptyState: "flex min-h-[120px] items-center justify-center text-center text-[var(--fg-secondary)]",
};
