import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass} !border-0 !shadow-none`;
const rowSurface = "rounded-[var(--radius-control)] bg-vui-surface-row";
const rowSurfaceSoft = "rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--vui-surface-row)_84%,var(--vui-surface-panel))]";
const controlSurface = "border border-vui-border-subtle bg-vui-control-muted hover:bg-vui-control-muted-hover";

export const selfEvolutionTrackStyles = {
  pageStack: "grid h-full max-h-full min-h-0 min-w-0 max-w-full overflow-hidden overflow-x-hidden bg-vui-surface-panel",
  trackShell: `grid h-full max-h-full min-h-0 min-w-0 max-w-full grid-rows-[minmax(0,1fr)] items-stretch overflow-hidden overflow-x-hidden !rounded-none !border-0 ${vuiFlatPanelClass} !shadow-none`,
  trackBody:
    "flex min-h-0 min-w-0 max-w-full flex-col overflow-hidden overflow-x-hidden",
  trackBodyContent:
    "min-h-0 min-w-0 max-w-full flex-1 overflow-hidden overflow-x-hidden",
  primaryAction:
    "inline-flex min-h-8 w-fit max-w-full cursor-pointer items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-control-muted))] px-3 [font-size:var(--vui-font-sm)] font-semibold text-vui-fg-primary disabled:cursor-default disabled:opacity-50",
  dangerAction:
    "inline-flex min-h-8 w-fit max-w-full cursor-pointer items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_9%,var(--vui-control-muted))] px-3 [font-size:var(--vui-font-sm)] font-semibold text-[var(--state-error)] disabled:cursor-default disabled:opacity-50",
  workspaceLayout:
    "grid h-full max-h-full min-h-0 min-w-0 max-w-full grid-cols-[var(--self-sidebar-width,340px)_10px_minmax(0,1fr)] items-stretch overflow-hidden overflow-x-hidden",
  sideColumn: "grid min-w-0 content-start bg-vui-surface-rail",
  sideColumnScrollable: "h-full overflow-y-auto",
  paneCollapsed: "overflow-hidden p-0 invisible",
  centerColumn: "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] overflow-hidden overflow-x-hidden bg-vui-surface-panel",
  conversationShell: "grid h-full max-h-full min-h-0 min-w-0 max-w-full overflow-hidden overflow-x-hidden rounded-none border-0 bg-vui-surface-panel [&_.vui-components-conversationview.surface]:!rounded-none [&_.vui-components-conversationview.surface]:!border-0 [&_.vui-components-conversationview.surface]:!shadow-none [&_.vui-components-conversationview.composer]:!border-t-0",
  observationEvidenceRail:
    `grid h-full max-h-full min-h-0 content-start gap-3 overflow-auto p-3.5 max-[1180px]:h-auto max-[1180px]:max-h-none ${panelSurface}`,
  observationConfigForm: "grid gap-2.5",
  observationConfigActions: "flex flex-wrap items-center gap-2",
  observationEventTimeline: `grid gap-2 p-2.5 ${rowSurfaceSoft}`,
  observationEventItem:
    `grid gap-1.5 px-2.5 py-2 ${rowSurfaceSoft} [&_strong]:overflow-wrap-anywhere [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  tooltipBlock: "grid max-w-[360px] gap-1 [&_strong]:font-semibold [&_span]:text-vui-fg-secondary",
  railSection: "grid gap-2.5 px-3.5 py-3",
  railSectionHeader: "flex min-w-0 items-center gap-1.5",
  railSectionTitle: "inline-flex min-w-0 flex-1 items-center gap-1.5 [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-[0.06em] text-vui-fg-secondary",
  railSectionActions: "flex shrink-0 items-center gap-1",
  railFactGrid: "grid grid-cols-2 gap-1.5",
  railFact: `grid min-w-0 gap-0.5 px-2.5 py-2 ${rowSurfaceSoft} focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:text-vui-fg-tertiary [&>strong]:truncate [&>strong]:text-[0.9rem] [&>strong]:text-vui-fg-primary`,
  railFieldLabel: "inline-flex items-center gap-1.5",
  railGoalInput: "min-h-[76px] resize-y bg-vui-surface-panel [font-size:var(--vui-font-xs)]",
  railActionRow: "flex min-w-0 items-center gap-2",
  railPrimaryAction: "min-w-0 flex-1",
  railFeedbackStack: "flex min-w-0 items-start gap-1.5 [&_p]:min-w-0 [&_p]:flex-1",
  railAgentSection: "grid gap-2 px-3.5 py-3",
  railAgentCount: "font-mono [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  railAgentActions: "flex min-h-8 min-w-0 flex-wrap items-center gap-1.5",
  railAgentGroup: "inline-flex items-center gap-1",
  railAgentButton: "h-8 w-8 min-w-8 p-0",
  railAgentButtonActive: "border-[color-mix(in_srgb,var(--accent-cool)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-control-muted))] text-vui-fg-primary",
  railEmptyValue: "font-mono text-vui-fg-tertiary",
  workflowHeader: "flex min-h-10 min-w-0 items-center px-2 py-1",
  workflowCardGrid: "inline-flex w-fit min-w-0 max-w-full items-center gap-1",
  workflowCard:
    "h-8 w-8 min-w-8 cursor-pointer rounded-md border border-transparent bg-transparent p-0 text-vui-fg-secondary",
  workflowCardActive:
    "!border-transparent bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-surface-row))] text-vui-fg-primary [&_strong]:text-[var(--accent-cool)]",
  approvalPanel: `grid min-h-0 content-start gap-3 overflow-auto p-3.5 ${panelSurface}`,
  statusDetailScroll: "grid h-full min-h-0 content-start gap-3 overflow-y-auto p-3",
  statusPage: "grid min-h-0",
  panelStack: "grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-4 overflow-hidden",
  // Wave 6A: PaneCollapseHandle owns the visual rule; breakpoint hide only.
  sidebarResizer: "",
  modeTabs: "inline-grid w-fit max-w-full min-w-0 gap-0",
  modeTabsList:
    "inline-flex w-fit max-w-full flex-wrap items-center gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-1",
  modeTabsTrigger:
    "min-h-8 w-fit rounded-md border border-transparent px-3 py-1 [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)] " +
    "data-[state=active]:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] " +
    "data-[state=active]:bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] " +
    "data-[state=active]:font-semibold data-[state=active]:text-[var(--accent-warm-2)]",
  surface: `${panelSurface} p-3.5 max-[760px]:p-4`,
  loadingShell:
    "grid min-h-[148px] max-h-[180px] content-start self-start overflow-hidden grid-cols-[minmax(240px,300px)_minmax(0,1fr)] gap-2 max-[1180px]:min-h-[172px] max-[1180px]:max-h-[210px] max-[1180px]:grid-cols-1",
  loadingRail: `grid min-h-0 content-start gap-2.5 p-3 ${rowSurfaceSoft}`,
  loadingPanel:
    `grid min-h-0 content-start gap-2 p-3 ${rowSurfaceSoft} [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-secondary`,
  loadingStatGrid:
    "grid grid-cols-3 gap-1.5 [&_span]:grid [&_span]:min-w-0 [&_span]:gap-1 [&_span]:rounded-[7px] [&_span]:bg-vui-surface-row [&_span]:px-[7px] [&_span]:py-1.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:font-mono [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  loadingBody: "grid min-h-0 grid-cols-3 gap-2",
  skeletonLineWide: "block h-2 w-[min(100%,620px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  skeletonLine: "block h-2 w-[min(72%,460px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  skeletonLineShort: "block h-2 w-[min(42%,260px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  sectionHeader: "flex items-start justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  itemTop: "flex items-center justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  detailRow:
    "flex items-center justify-between gap-3 pb-2 max-[760px]:flex-col max-[760px]:items-stretch [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:overflow-wrap-anywhere [&_strong]:text-[0.92rem] [&_strong]:text-[var(--fg-primary)]",
  paginationBar: "flex flex-wrap items-center justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  subsurfaceHeader: "flex items-start justify-between gap-3 max-[760px]:flex-col max-[760px]:items-stretch",
  eyebrow: "m-0 mb-1 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  sectionTitle: "m-0 text-base text-[var(--fg-primary)]",
  subsurfaceTitle: "m-0 text-[0.98rem] text-[var(--fg-primary)]",
  subsectionTitle: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)]",
  sectionSummary: "m-0 leading-normal text-[var(--fg-secondary)]",
  mutedText: "m-0 leading-normal text-[var(--fg-secondary)]",
  noticeText: "m-0 leading-normal text-[var(--fg-secondary)]",
  feedbackText: "m-0 overflow-wrap-anywhere leading-normal text-[var(--accent-warm-2)]",
  errorText: "m-0 overflow-wrap-anywhere leading-normal text-[var(--state-error)]",
  statusIcon: "inline-flex h-8 w-8 flex-none items-center justify-center rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] text-[var(--accent-cool)]",
  statusPill:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] px-2.5 [font-size:var(--vui-font-xs)] text-[var(--accent-warm-2)] max-[760px]:w-fit",
  secondaryPill:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-subtle bg-vui-control-muted px-2.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:w-fit",
  counter:
    "inline-flex min-h-7 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-subtle bg-vui-control-muted px-2.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:w-fit",
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
    "grid gap-1.5 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)]",
  textInput: "w-full max-w-[180px]",
  textArea: "w-full",
  worktreeEscalation:
    "flex items-center justify-between gap-3 rounded-[var(--radius-panel)] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] px-3.5 py-3 [&_p]:flex-[1_1_220px]",
  supportGrid: "grid gap-4",
  subsurface:
    `grid min-h-0 content-start gap-3 overflow-auto p-3.5 ${panelSurface}`,
  listItem:
    `grid gap-2 px-[13px] py-3 ${rowSurfaceSoft} [&_strong]:overflow-wrap-anywhere [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
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
    "absolute bottom-2.5 left-2.5 inline-flex min-h-7 items-center gap-1.5 rounded-full border border-vui-border-subtle bg-vui-control-muted px-2.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary",
  petCompanionCopy: "grid gap-1.5 [&_p]:m-0 [&_p]:text-[0.92rem] [&_p]:leading-normal [&_p]:text-[var(--fg-primary)] [&_span]:m-0 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-normal [&_span]:text-[var(--fg-secondary)]",
  supportColumns: "grid min-h-0 grid-cols-2 gap-4 max-[1180px]:grid-cols-1",
  subsectionGrid: "grid min-h-0 grid-cols-2 gap-4 max-[1180px]:grid-cols-1",
  headerIcon: "flex-none text-[var(--fg-tertiary)]",
  metricStrip: "grid grid-cols-4 gap-3 max-[1180px]:grid-cols-1 max-[760px]:grid-cols-2",
  stripItem:
    `grid min-h-[58px] gap-1 px-2.5 py-[9px] ${rowSurfaceSoft} [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:overflow-wrap-anywhere [&_strong]:text-[0.92rem] [&_strong]:text-vui-fg-primary`,
  compactMetricGrid: "grid grid-cols-2 gap-2 max-[760px]:grid-cols-1",
  observationMetricGrid: "grid grid-cols-3 gap-2 max-[900px]:grid-cols-1",
  historyToolbar: "flex flex-wrap items-center justify-between gap-3",
  transactionFilterBar: "flex flex-wrap gap-2",
  transactionDateFilterBar:
    "flex flex-wrap items-center gap-2 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:leading-tight [&>span]:text-[var(--fg-tertiary)]",
  transactionVisibleSummary:
    "inline-flex min-h-[30px] items-center whitespace-nowrap font-mono [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  transactionFilterButton:
    `inline-flex min-h-[34px] w-fit max-w-full cursor-pointer items-center gap-2 rounded-[var(--radius-control)] px-2.5 text-vui-fg-secondary ${controlSurface} [&_strong]:min-w-[22px] [&_strong]:text-right [&_strong]:font-mono [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
  transactionFilterButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]",
  transactionDetailsToggle:
    "inline-flex min-h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_78%,transparent)] px-[9px] [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] aria-expanded:border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] aria-expanded:text-[var(--accent-cool)]",
  transactionDateGroup:
    "grid gap-2 pt-0.5 [&+&]:mt-3 [&+&]:pt-1",
  transactionDateHeader:
    "flex min-h-[30px] items-center justify-between gap-2.5 px-0.5 max-[760px]:flex-col max-[760px]:items-stretch [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-tertiary)]",
  transactionGroupList: "grid gap-2",
  selectionToggle:
    `inline-flex min-h-8 w-fit max-w-full cursor-pointer items-center gap-2 rounded-[var(--radius-control)] px-3 text-vui-fg-secondary disabled:cursor-default disabled:opacity-50 ${controlSurface}`,
  checkboxRow: "inline-flex items-center gap-2.5 text-[var(--fg-primary)] [&_input]:h-[15px] [&_input]:w-[15px]",
  transactionTitleStack:
    "grid min-w-0 gap-1 [&_span]:overflow-wrap-anywhere [&_span]:font-mono [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-tertiary)]",
  transactionMetaGrid: `grid grid-cols-4 gap-1.5 max-[1180px]:grid-cols-2 [&_span]:min-w-0 [&_span]:overflow-wrap-anywhere [&_span]:rounded-[var(--radius-control)] [&_span]:${vuiOpaqueRowClass} [&_span]:!border-0 [&_span]:px-2 [&_span]:py-1.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-secondary)]`,
  transactionGoalPreview: "m-0 overflow-wrap-anywhere [font-size:var(--vui-font-xs)] leading-normal text-[var(--fg-secondary)]",
  previewText: "m-0 overflow-wrap-anywhere text-[0.92rem] leading-normal text-[var(--fg-primary)]",
  compactPreviewText: "m-0 line-clamp-2 overflow-wrap-anywhere [font-size:var(--vui-font-xs)] leading-normal text-[var(--fg-secondary)]",
  rawBlock: `overflow-auto rounded-[var(--radius-panel)] ${vuiOpaqueRowClass} !border-0 p-3 font-mono [font-size:var(--vui-font-xs)] leading-relaxed text-[var(--fg-secondary)]`,
  transactionDetailsPanel:
    `grid grid-cols-2 gap-2 p-[9px] max-[1180px]:grid-cols-1 ${rowSurfaceSoft}`,
  transactionDetailRow:
    "grid min-w-0 gap-1 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:overflow-wrap-anywhere [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:leading-snug [&_strong]:text-[var(--fg-secondary)]",
  vitalList: "grid gap-2",
  vitalItem: "grid gap-1.5",
  vitalTrack: "h-2 w-full overflow-hidden rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--fg-secondary)_70%,transparent)]",
  vitalFill: "h-full w-[var(--self-vital-progress)] rounded-[var(--radius-control)] bg-[var(--vui-gradient-route-soft)]",
  paginationGroup: "flex flex-wrap items-center gap-2",
  emptyState: "flex min-h-[120px] items-center justify-center text-center text-[var(--fg-secondary)]",
} as const;
