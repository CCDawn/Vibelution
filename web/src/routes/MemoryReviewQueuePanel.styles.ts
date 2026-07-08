const styles = {
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  emptyState:
    "emptyState min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  reviewQueueActions:
    "reviewQueueActions min-w-0 flex flex-wrap items-center gap-1.5 grid min-h-0 content-start overflow-auto",
  reviewQueueBody:
    "reviewQueueBody min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  reviewQueueItem:
    "reviewQueueItem min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  reviewQueueList:
    "reviewQueueList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto overflow-auto",
  reviewQueueSummary:
    "reviewQueueSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid min-h-0 content-start gap-1.5 overflow-auto",
  reviewQueueTime:
    "reviewQueueTime min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  reviewQueueTitleLine:
    "reviewQueueTitleLine min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)] !grid grid-cols-[minmax(0,0.62fr)_minmax(82px,0.38fr)] items-baseline gap-2",
  reviewRank:
    "reviewRank min-w-0",
  reviewReasonList:
    "reviewReasonList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] hidden",
  reviewReasonPill:
    "reviewReasonPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)]",
} as const;

export default styles;
