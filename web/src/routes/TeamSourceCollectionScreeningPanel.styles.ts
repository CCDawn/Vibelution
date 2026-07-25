const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  sourceCollectionPanelActions:
    "sourceCollectionPanelActions min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color:var(--source-workbench-card)] p-1.5 !flex flex-wrap items-center justify-start gap-1.5 [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full",
  sourceCollectionScreeningList:
    "sourceCollectionScreeningList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  // Wave 6E: height from PersistedHeightListShell / pane-heights.v1, not fixed max-h.
  sourceCollectionScreeningListShell:
    "sourceCollectionScreeningListShell min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-card)] p-1.5 text-[var(--fg-primary)] items-start self-start [scrollbar-gutter:stable]",
  sourceCollectionListResizeHandle:
    "sourceCollectionListResizeHandle",
  sourceCollectionScreeningScrollHint:
    "sourceCollectionScreeningScrollHint min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowIngestionActions:
    "workflowIngestionActions min-w-0 flex flex-wrap items-center gap-1.5",
  workflowSourceQualityStats:
    "workflowSourceQualityStats min-w-0 grid gap-2 !grid grid-cols-[repeat(5,minmax(72px,1fr))] gap-[5px]",
} as const;

export default styles;
