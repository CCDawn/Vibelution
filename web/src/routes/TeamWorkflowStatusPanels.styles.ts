const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  messageError:
    "messageError min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)] text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  workflowCoordinationBriefSummary:
    "workflowCoordinationBriefSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowCoordinationPanel:
    "workflowCoordinationPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowCoordinationQueue:
    "workflowCoordinationQueue min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowCoordinationQueues:
    "workflowCoordinationQueues min-w-0",
  workflowCoordinationStats:
    "workflowCoordinationStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  workflowGraphBoundary:
    "workflowGraphBoundary min-w-0",
  workflowGraphHeader:
    "workflowGraphHeader min-w-0 flex flex-wrap items-center gap-1.5",
  workflowGraphIssues:
    "workflowGraphIssues min-w-0",
  workflowGraphPanel:
    "workflowGraphPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowGraphStats:
    "workflowGraphStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  workflowIngestionActions:
    "workflowIngestionActions min-w-0 flex flex-wrap items-center gap-1.5",
  workflowIngestionBoundary:
    "workflowIngestionBoundary min-w-0",
  workflowIngestionHeader:
    "workflowIngestionHeader min-w-0 flex flex-wrap items-center gap-1.5",
  workflowIngestionPanel:
    "workflowIngestionPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowIngestionStage:
    "workflowIngestionStage min-w-0",
  workflowIngestionStages:
    "workflowIngestionStages min-w-0 !grid grid-cols-[repeat(5,minmax(58px,1fr))] gap-1",
  workflowIngestionStats:
    "workflowIngestionStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  workflowModelEvidenceCoverage:
    "workflowModelEvidenceCoverage min-w-0 !grid grid-cols-[repeat(auto-fit,minmax(118px,1fr))] gap-1.5",
  workflowModelEvidencePanel:
    "workflowModelEvidencePanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowModelEvidenceStats:
    "workflowModelEvidenceStats min-w-0 grid gap-2 !grid grid-cols-[repeat(auto-fit,minmax(118px,1fr))] gap-1.5",
  workflowPaperNoteChunkPanel:
    "workflowPaperNoteChunkPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowPaperNoteChunkPlans:
    "workflowPaperNoteChunkPlans min-w-0 !grid grid-cols-[repeat(2,minmax(0,1fr))] gap-[5px]",
  workflowPaperNoteChunkStats:
    "workflowPaperNoteChunkStats min-w-0 grid gap-2 !grid grid-cols-[repeat(4,minmax(86px,1fr))] gap-[5px]",
  workflowSourceQualityPanel:
    "workflowSourceQualityPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  workflowSourceQualityQueue:
    "workflowSourceQualityQueue min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto !grid grid-cols-[repeat(3,minmax(0,1fr))] gap-[5px]",
  workflowSourceQualityStats:
    "workflowSourceQualityStats min-w-0 grid gap-2 !grid grid-cols-[repeat(5,minmax(72px,1fr))] gap-[5px]",
  workflowTag:
    "workflowTag min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  workflowTagDanger:
    "workflowTagDanger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  workflowTagNeutral:
    "workflowTagNeutral min-w-0",
  workflowTagReady:
    "workflowTagReady min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  workflowTagWarning:
    "workflowTagWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
} as const;

export default styles;
