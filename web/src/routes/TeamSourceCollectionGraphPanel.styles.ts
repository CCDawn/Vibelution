const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  sourceCollectionGraphNodeListShell:
    "sourceCollectionGraphNodeListShell min-w-0 max-w-full grid max-h-[28vh] min-h-[96px] content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[color:var(--border-soft)] bg-[var(--vui-surface-panel)] p-1.5 text-[var(--fg-primary)] [scrollbar-gutter:stable] max-[860px]:max-h-[34vh]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [&_[data-vui-product=team-candidate-card]]:max-w-full [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full",
  workflowGraphStats:
    "workflowGraphStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
} as const;

export default styles;
