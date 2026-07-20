const styles = {
  section: "min-w-0",
  body: "m-0 max-w-4xl text-sm leading-6 text-[var(--vui-text-secondary)]",
  grid: "grid min-w-0 grid-cols-1 gap-2 lg:grid-cols-2",
  card:
    "flex min-w-0 items-start gap-3 rounded-xl border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-4 py-3",
  enabledIcon: "mt-0.5 text-[var(--vui-status-success)]",
  disabledIcon: "mt-0.5 text-[var(--vui-text-tertiary)]",
  cardContent: "min-w-0 flex-1",
  cardHeader: "flex min-w-0 items-center justify-between gap-3",
  cardTitle: "truncate text-sm text-[var(--vui-text-primary)]",
  cardStatus: "shrink-0 text-xs text-[var(--vui-text-secondary)]",
  reason: "m-0 mt-1 text-xs leading-5 text-[var(--vui-text-secondary)]",
  provenance: "m-0 mt-1 flex items-center gap-1 font-mono text-[11px] text-[var(--vui-text-tertiary)]",
} as const;

export default styles;
