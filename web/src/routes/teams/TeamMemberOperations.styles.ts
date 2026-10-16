export default {
  panel: "flex min-w-0 flex-col gap-3 p-4",
  heading: "flex min-w-0 flex-col gap-1 text-sm font-semibold text-[var(--fg-primary)]",
  name: "break-words text-xs font-normal text-[var(--fg-secondary)]",
  action: "min-h-11 w-full",
  fields: "flex min-w-0 flex-col gap-3 rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3",
  field: "flex min-w-0 flex-col gap-1.5 text-xs text-[var(--fg-secondary)]",
  select: "min-h-11 w-full min-w-0",
  hint: "break-words text-xs text-[var(--fg-secondary)]",
  error: "break-words text-xs text-[var(--fg-danger,crimson)]",
} as const;
