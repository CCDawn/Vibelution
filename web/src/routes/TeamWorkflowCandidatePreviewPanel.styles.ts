const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowCandidateListHeader:
    "workflowCandidateListHeader min-w-0 flex flex-wrap items-center gap-1.5 grid min-h-0 content-start overflow-auto",
  workflowCandidateListPanel:
    "workflowCandidateListPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowCandidateListScroll:
    "workflowCandidateListScroll min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowCandidateListScrollHint:
    "workflowCandidateListScrollHint min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
