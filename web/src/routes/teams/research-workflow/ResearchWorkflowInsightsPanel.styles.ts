export default {
  loading: "min-h-20 animate-pulse",
  error: "p-3 text-sm text-[var(--state-error)]",
  empty: "h-auto border-0 bg-transparent",
  root: "space-y-3 p-3",
  metrics: "m-0 grid grid-cols-2 gap-2 text-xs",
  metric: "rounded border border-[var(--border-subtle)] p-2",
  label: "text-[var(--fg-tertiary)]",
  value: "m-0 text-base font-semibold",
  detail: "m-0 grid grid-cols-[88px_1fr] gap-x-2 gap-y-1 text-xs",
  detailValue: "m-0",
  blocking: "m-0 text-[var(--state-error)]",
} as const;
