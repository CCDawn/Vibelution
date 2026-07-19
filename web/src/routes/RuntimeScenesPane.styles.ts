const panelSurface =
  "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] p-2";
const rowSurface =
  "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_74%,transparent)] p-2";
const buttonBase =
  "inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55";
const pillBase =
  "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]";
const activeTone =
  "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]";
const errorTone =
  "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]";
const warningTone =
  "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]";
const successTone =
  "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]";
const scrollStack = "grid min-h-0 content-start gap-1.5 overflow-auto";

const styles = {
  copyButton:
    `copyButton min-w-0 ${buttonBase} [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)]`,
  deleteButton:
    `deleteButton min-w-0 ${buttonBase} ${errorTone}`,
  diagnosticHintGrid:
    "diagnosticHintGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  diagnosticMetricGrid:
    "diagnosticMetricGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  diagnosticPill:
    `diagnosticPill min-w-0 ${pillBase}`,
  diagnosticPillError:
    "diagnosticPillError min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  diagnosticPillInfo:
    "diagnosticPillInfo min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  diagnosticPillWarning:
    "diagnosticPillWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  diagnosticsHeader:
    "diagnosticsHeader min-w-0 flex flex-wrap items-center gap-1.5",
  diagnosticsPanel:
    `diagnosticsPanel min-w-0 ${panelSurface}`,
  diagnosticsSummary:
    `diagnosticsSummary min-w-0 ${panelSurface}`,
  emptySurface:
    `emptySurface min-w-0 ${panelSurface} [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  eyebrow:
    "eyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  filterButton:
    `filterButton min-w-0 ${buttonBase}`,
  filterButtonActive:
    `filterButtonActive min-w-0 ${activeTone}`,
  filterGroup:
    "filterGroup min-w-0",
  logPreviewStack:
    `logPreviewStack min-w-0 ${panelSurface} font-mono [font-size:var(--vui-font-xs)]`,
  metaPill:
    `metaPill min-w-0 flex flex-wrap ${pillBase}`,
  notice:
    `notice min-w-0 ${panelSurface}`,
  noticeError:
    `noticeError min-w-0 ${panelSurface} ${errorTone}`,
  noticeSuccess:
    `noticeSuccess min-w-0 ${panelSurface} ${successTone}`,
  packageClusterItem:
    `packageClusterItem min-w-0 ${rowSurface}`,
  packageClusterList:
    `packageClusterList min-w-0 ${scrollStack}`,
  packageClusterRefs:
    "packageClusterRefs min-w-0",
  packageDiagnosisDetails:
    "packageDiagnosisDetails min-w-0",
  packageDiagnosisExpandLabel:
    "packageDiagnosisExpandLabel min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  packageDiagnosisFoldout:
    "packageDiagnosisFoldout min-w-0",
  packageDiagnosisFoldoutSection:
    "packageDiagnosisFoldoutSection min-w-0",
  packageDiagnosisGrid:
    "packageDiagnosisGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  packageDiagnosisHeader:
    "packageDiagnosisHeader min-w-0 flex flex-wrap items-center gap-1.5",
  packageDiagnosisInlineMetrics:
    "packageDiagnosisInlineMetrics min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  packageDiagnosisPanel:
    `packageDiagnosisPanel min-w-0 ${panelSurface}`,
  packageDiagnosisSummary:
    `packageDiagnosisSummary min-w-0 ${panelSurface}`,
  packageDiagnosisSummaryRow:
    `packageDiagnosisSummaryRow min-w-0 ${rowSurface}`,
  packageDiagnosisSummaryText:
    `packageDiagnosisSummaryText min-w-0 ${panelSurface} [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]`,
  packageEvidencePaths:
    "packageEvidencePaths min-w-0",
  packageIssueStateStrip:
    "packageIssueStateStrip min-w-0 flex flex-wrap items-center gap-1.5",
  packageKeyEntries:
    "packageKeyEntries min-w-0",
  packageKeyEntryButton:
    `packageKeyEntryButton min-w-0 ${buttonBase}`,
  packageList:
    `packageList min-w-0 ${scrollStack}`,
  packagePrimaryCluster:
    `packagePrimaryCluster min-w-0 ${activeTone}`,
  packageReadingOrder:
    "packageReadingOrder min-w-0",
  packageSection:
    "packageSection min-w-0",
  packageSectionEmpty:
    "packageSectionEmpty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  packageSectionHeader:
    "packageSectionHeader min-w-0 flex flex-wrap items-center gap-1.5",
  packageSectionList:
    `packageSectionList min-w-0 ${scrollStack}`,
  packageSelectButton:
    `packageSelectButton min-w-0 ${buttonBase} grid gap-1 [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full`,
  packageSelectButtonActive:
    `packageSelectButtonActive min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full ${activeTone}`,
  packageWorkRunHeader:
    "packageWorkRunHeader min-w-0 flex flex-wrap items-center gap-1.5",
  packageWorkRunItem:
    `packageWorkRunItem min-w-0 ${rowSurface}`,
  packageWorkRunList:
    `packageWorkRunList min-w-0 ${scrollStack}`,
  packageWorkRunMetricStrip:
    "packageWorkRunMetricStrip min-w-0 flex flex-wrap items-center gap-1.5",
  packageWorkRunPanel:
    `packageWorkRunPanel min-w-0 ${panelSurface}`,
  packageWorkRunPathButton:
    `packageWorkRunPathButton min-w-0 ${buttonBase} font-mono`,
  paneCollapsed:
    "paneCollapsed min-w-0 hidden",
  panelSearch:
    `panelSearch min-w-0 ${panelSurface}`,
  panelSearchInput:
    `panelSearchInput min-w-0 ${panelSurface} grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full`,
  panelState:
    `panelState min-w-0 ${panelSurface}`,
  previewActions:
    `previewActions min-w-0 ${panelSurface} flex flex-wrap items-center gap-1.5`,
  previewPane:
    `previewPane min-w-0 ${panelSurface} grid min-h-0 content-start gap-1.5 overflow-auto`,
  railText:
    "railText min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  rawFileButton:
    `rawFileButton min-w-0 ${buttonBase}`,
  rawFileButtonActive:
    `rawFileButtonActive min-w-0 ${activeTone}`,
  rawFileTabs:
    "rawFileTabs min-w-0",
  resizableLayout:
    "resizableLayout min-w-0 max-w-full grid h-full min-h-0 gap-2 p-2 !grid grid-cols-[var(--logs-sidebar-width)_auto_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden overflow-x-hidden max-[900px]:grid-cols-[minmax(0,1fr)] max-[900px]:grid-rows-[max-content_minmax(0,1fr)]",
  resizeHandle:
    "resizeHandle min-w-0",
  resizeHandleActive:
    `resizeHandleActive min-w-0 ${activeTone}`,
  sceneCard:
    `sceneCard min-w-0 ${panelSurface}`,
  sceneCardActive:
    `sceneCardActive min-w-0 ${panelSurface} ${activeTone}`,
  sceneCardButton:
    `sceneCardButton min-w-0 ${buttonBase}`,
  sceneCardHeader:
    `sceneCardHeader min-w-0 ${panelSurface} flex flex-wrap items-center gap-1.5`,
  sceneCardHeaderRow:
    `sceneCardHeaderRow min-w-0 ${rowSurface} flex flex-wrap items-center gap-1.5`,
  sceneCardMeta:
    `sceneCardMeta min-w-0 ${panelSurface} flex flex-wrap items-center gap-1.5`,
  sceneCardStatus:
    `sceneCardStatus min-w-0 ${panelSurface}`,
  sceneCardStatusGroup:
    `sceneCardStatusGroup min-w-0 ${panelSurface}`,
  sceneCardSummary:
    `sceneCardSummary min-w-0 ${panelSurface}`,
  sceneCardTop:
    `sceneCardTop min-w-0 ${panelSurface}`,
  sceneDetailHeaderCompact:
    `sceneDetailHeaderCompact min-w-0 ${panelSurface} flex flex-wrap items-center gap-1.5`,
  sceneDetailSummary:
    `sceneDetailSummary min-w-0 ${panelSurface}`,
  sceneDetailSurface:
    `sceneDetailSurface min-w-0 ${panelSurface}`,
  sceneDetailTitle:
    `sceneDetailTitle min-w-0 ${panelSurface} [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]`,
  sceneEvidenceStrip:
    "sceneEvidenceStrip min-w-0 flex flex-wrap items-center gap-1.5",
  sceneHeaderControls:
    "sceneHeaderControls min-w-0 flex flex-wrap items-center gap-1.5",
  sceneIdentityBlock:
    "sceneIdentityBlock min-w-0 grid gap-1",
  sceneIndexKey:
    "sceneIndexKey min-w-0",
  sceneInfoCard:
    `sceneInfoCard min-w-0 ${panelSurface} border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]`,
  sceneInfoGrid:
    "sceneInfoGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  sceneIssueBadge:
    "sceneIssueBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  sceneIssueBadgeError:
    "sceneIssueBadgeError min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  sceneIssueBadgeWarning:
    "sceneIssueBadgeWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  scenePillRow:
    `scenePillRow min-w-0 ${rowSurface}`,
  sceneQuickFacts:
    "sceneQuickFacts min-w-0",
  sceneRawHeader:
    "sceneRawHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sceneRawPreview:
    `sceneRawPreview min-w-0 ${panelSurface}`,
  sceneTechnicalDetails:
    "sceneTechnicalDetails min-w-0",
  sceneTechnicalGrid:
    "sceneTechnicalGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  selectionActions:
    "selectionActions min-w-0 flex flex-wrap items-center gap-1.5",
  selectionPill:
    "selectionPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  selectionToolbar:
    "selectionToolbar min-w-0 flex flex-wrap items-center gap-1.5",
  sidebar:
    "sidebar min-w-0",
  sidebarEyebrow:
    "sidebarEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  sidebarHeader:
    "sidebarHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sidebarTitle:
    "sidebarTitle min-w-0 [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  startupTraceHeader:
    "startupTraceHeader min-w-0 flex flex-wrap items-center gap-1.5",
  startupTracePanel:
    `startupTracePanel min-w-0 ${panelSurface}`,
  startupTraceStep:
    "startupTraceStep min-w-0",
  startupTraceStepMissing:
    "startupTraceStepMissing min-w-0",
  startupTraceSteps:
    "startupTraceSteps min-w-0",
  timelineCode:
    "timelineCode min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto font-mono [font-size:var(--vui-font-xs)]",
  timelineField:
    "timelineField min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  timelineFields:
    "timelineFields min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  timelineHeader:
    "timelineHeader min-w-0 flex flex-wrap items-center gap-1.5 grid min-h-0 content-start overflow-auto",
  timelineItem:
    `timelineItem min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${rowSurface}`,
  timelineItemError:
    `timelineItemError min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${rowSurface} ${errorTone}`,
  timelineItemWarning:
    `timelineItemWarning min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${rowSurface} ${warningTone}`,
  timelineList:
    "timelineList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  timelineMessage:
    "timelineMessage min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  timelineRawRefs:
    "timelineRawRefs min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  toolbarButton:
    `toolbarButton min-w-0 flex flex-wrap items-center ${buttonBase}`,
} as const;

export default styles;
