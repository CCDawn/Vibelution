const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [&_[data-vui-product=team-candidate-card]]:max-w-full",
  workflowCandidateListHeader:
    "workflowCandidateListHeader min-w-0 grid min-h-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 max-[760px]:grid-cols-[minmax(0,1fr)] [&>div:first-child]:grid [&>div:first-child]:min-w-0 [&>div:first-child]:gap-0.5 [&>div:first-child>strong]:truncate [&>div:first-child>span]:min-w-0 [&>div:first-child>span]:break-words [&>div:first-child>span]:text-[var(--fg-muted)] [&>div:last-child]:flex [&>div:last-child]:min-w-0 [&>div:last-child]:flex-wrap [&>div:last-child]:items-center [&>div:last-child]:justify-end [&>div:last-child]:gap-1.5 max-[760px]:[&>div:last-child]:justify-start [&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:whitespace-nowrap",
  workflowCandidateListPanel:
    "workflowCandidateListPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid min-h-0 content-start gap-1.5 overflow-hidden",
  workflowCandidateListScroll:
    "workflowCandidateListScroll min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [scrollbar-gutter:stable]",
  workflowCandidateListScrollHint:
    "workflowCandidateListScrollHint min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
