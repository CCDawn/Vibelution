const styles = {
  sourceCollectionSearchEvidence:
    "sourceCollectionSearchEvidence min-w-0",
  sourceCollectionSearchEvidenceBody:
    "sourceCollectionSearchEvidenceBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-[5px] min-w-0 [&>span]:grid [&>span]:gap-0.5 [&>span]:min-w-0 [&_a]:inline-flex [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[28px] [&_a]:px-2.5 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--surface-panel-strong))] [&_a]:text-[var(--fg-primary)] [&_a]:font-[780] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:gap-1.5 [&_[data-vui=native-button]]:min-h-[28px] [&_[data-vui=native-button]]:px-2.5 [&_[data-vui=native-button]]:rounded-[7px] [&_[data-vui=native-button]]:border [&_[data-vui=native-button]]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_[data-vui=native-button]]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--surface-panel-strong))] [&_[data-vui=native-button]]:text-[var(--fg-primary)] [&_[data-vui=native-button]]:font-[780]",
  sourceCollectionSourceDetailActions:
    "sourceCollectionSourceDetailActions min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-1.5 !flex flex-wrap items-center gap-1.5 [&_a]:inline-flex [&_a]:w-fit [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[28px] [&_a]:px-2.5 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--surface-panel-strong))] [&_a]:text-[var(--fg-primary)] [&_a]:font-[780] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full",
  sourceCollectionSourceDetailFacts:
    "sourceCollectionSourceDetailFacts min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-1.5 !grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-[5px] [&_span]:min-w-0 [&_code]:truncate",
  sourceCollectionSourceDetailHeader:
    "sourceCollectionSourceDetailHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-1.5 max-[720px]:grid-cols-[1fr] [&_div]:min-w-0 [&_strong]:block [&_strong]:truncate [&_span]:truncate",
  sourceCollectionSourceDetailNotice:
    "sourceCollectionSourceDetailNotice min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  sourceCollectionSourceDetailPanel:
    "sourceCollectionSourceDetailPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 !grid content-start gap-2",
  workflowTag:
    "workflowTag min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
