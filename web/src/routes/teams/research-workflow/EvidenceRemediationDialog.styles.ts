export default {
  form: "grid gap-4",
  scopeList: "grid max-h-44 gap-1 overflow-y-auto rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  candidate: "min-w-0 truncate font-mono [font-size:var(--vui-font-2xs)]",
  budgetGrid: "grid grid-cols-2 gap-3",
  error: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--vui-status-danger-fg)]",
} as const;
