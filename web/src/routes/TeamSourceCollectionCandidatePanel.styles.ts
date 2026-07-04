const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  sourceCollectionCandidateListShell:
    "sourceCollectionCandidateListShell min-w-0 grid max-h-[44vh] min-h-[220px] content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-card)] p-1.5 text-[var(--fg-primary)] items-start self-start [scrollbar-gutter:stable] max-[860px]:max-h-none",
  sourceCollectionCandidateSkeletonList:
    "sourceCollectionCandidateSkeletonList min-w-0 grid content-start gap-1.5",
  sourceCollectionCandidateSkeletonRow:
    "sourceCollectionCandidateSkeletonRow min-h-[56px] rounded-[var(--radius-control)] border border-[color:var(--border-subtle)] bg-[color:var(--surface-muted)] p-2",
  sourceCollectionCandidateSkeletonTitle:
    "sourceCollectionCandidateSkeletonTitle block h-3 w-2/3 rounded-[var(--radius-control)] bg-[color:var(--border-soft)]",
  sourceCollectionCandidateSkeletonMeta:
    "sourceCollectionCandidateSkeletonMeta mt-3 block h-2.5 w-1/3 rounded-[var(--radius-control)] bg-[color:var(--border-soft)]",
  sourceCollectionScreeningScrollHint:
    "sourceCollectionScreeningScrollHint min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowSourceQualityStats:
    "workflowSourceQualityStats min-w-0 grid gap-2 !grid grid-cols-[repeat(5,minmax(72px,1fr))] gap-[5px]",
} as const;

export default styles;
