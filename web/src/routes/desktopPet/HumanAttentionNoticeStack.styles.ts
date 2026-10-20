const styles = {
  stack: "pointer-events-none fixed right-2 top-8 z-10 flex w-[min(280px,calc(100%-16px))] flex-col gap-1.5",
  card: "pointer-events-auto relative flex min-w-0 items-stretch gap-0.5 rounded-[10px] border bg-[var(--vui-surface-panel)] pr-0.5 text-[var(--fg-primary)] opacity-100 shadow-lg transition-opacity duration-200 motion-reduce:transition-none data-[severity=critical]:border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] data-[severity=critical]:bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-panel))] data-[severity=high]:border-[color-mix(in_srgb,var(--state-warning)_34%,var(--vui-border-subtle))] data-[severity=high]:bg-[color-mix(in_srgb,var(--state-warning)_8%,var(--vui-surface-panel))] data-[severity=medium]:border-[var(--vui-border-subtle)]",
  cardMain: "flex min-h-0 w-full min-w-0 flex-1 flex-col items-start gap-0.5 whitespace-normal rounded-[9px] px-2 py-1.5 text-left hover:bg-[color-mix(in_srgb,var(--vui-selection-bg)_55%,transparent)]",
  cardCopy: "grid min-w-0 flex-1 gap-0.5",
  cardTitle: "w-full truncate text-[11px] font-medium leading-4",
  cardBody: "line-clamp-2 w-full text-[10px] leading-[14px] text-[var(--fg-secondary)]",
  cardKind: "text-[9px] leading-[12px] text-[var(--fg-secondary)] [[data-severity=critical]_&]:text-[color-mix(in_srgb,var(--state-error)_80%,var(--fg-secondary))] [[data-severity=high]_&]:text-[color-mix(in_srgb,var(--state-warning)_80%,var(--fg-secondary))]",
  cardIcon: "shrink-0 text-[var(--fg-secondary)] [[data-severity=critical]_&]:text-[var(--state-error)] [[data-severity=high]_&]:text-[var(--state-warning)]",
  cardClose: "absolute right-0.5 top-0.5 size-5 min-h-5 min-w-5 p-0 text-[var(--fg-secondary)] opacity-70 hover:opacity-100",
  cardColumn: "flex-col",
  cardActions: "flex w-full min-w-0 flex-wrap items-center gap-1 px-2 pb-1.5",
  gateActionButton: "min-h-6 rounded-md border border-[var(--vui-border-subtle)] px-2 py-0.5 text-[10px] leading-4 text-[var(--fg-secondary)] hover:bg-[color-mix(in_srgb,var(--vui-selection-bg)_55%,transparent)]",
  gateAcceptButton: "min-h-6 rounded-md border border-[color-mix(in_srgb,var(--state-success)_40%,var(--vui-border-subtle))] px-2 py-0.5 text-[10px] leading-4 text-[var(--fg-primary)] hover:bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)]",
  gateDangerButton: "min-h-6 rounded-md border border-[color-mix(in_srgb,var(--state-error)_45%,var(--vui-border-subtle))] px-2 py-0.5 text-[10px] leading-4 text-[color-mix(in_srgb,var(--state-error)_85%,var(--fg-primary))] hover:bg-[color-mix(in_srgb,var(--state-error)_12%,transparent)]",
  gateConfirmRow: "flex min-w-0 items-center gap-1",
  gateError: "w-full text-[9px] leading-[12px] text-[color-mix(in_srgb,var(--state-error)_85%,var(--fg-primary))]",
} as const;

export default styles;
