const styles = {
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  overviewGrid:
    "overviewGrid min-w-0 grid gap-2 grid-cols-[repeat(2,minmax(0,1fr))] gap-2 max-[900px]:grid-cols-1",
  overviewPanel:
    "overviewPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid grid-rows-[auto_minmax(0,1fr)] overflow-auto",
  panelEyebrow:
    "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  reviewQueuePanel:
    "reviewQueuePanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid min-h-0 content-start gap-1.5 overflow-auto max-h-[min(280px,34vh)] overflow-auto",
  summaryCard:
    "summaryCard min-w-[156px] max-w-[220px] rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] grid min-h-[44px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:truncate [&>span]:text-[var(--vui-font-xs)] [&>strong]:text-[var(--vui-font-title)]",
  summaryGrid:
    "summaryGrid min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid justify-start gap-1.5 grid-cols-[repeat(auto-fit,minmax(156px,max-content))] max-[720px]:grid-cols-2",
} as const;

export default styles;
