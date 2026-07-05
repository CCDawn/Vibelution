const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  sourceCollectionMemoryListShell:
    "sourceCollectionMemoryListShell min-w-0 grid max-h-[44vh] min-h-[220px] content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-card)] p-1.5 text-[var(--fg-primary)] items-start self-start [scrollbar-gutter:stable] max-[860px]:max-h-[58vh]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowIngestionActions:
    "workflowIngestionActions min-w-0 flex flex-wrap items-center gap-1.5",
  workflowIngestionBoundary:
    "workflowIngestionBoundary min-w-0",
  workflowSourceQualityStats:
    "workflowSourceQualityStats min-w-0 grid gap-2 !grid grid-cols-[repeat(5,minmax(72px,1fr))] gap-[5px]",
} as const;

export default styles;
