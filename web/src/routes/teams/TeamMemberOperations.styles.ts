export default {
  panel: "flex min-w-0 flex-col gap-3 p-4",
  heading: "flex min-w-0 flex-col gap-1 text-vui-xs [line-height:var(--tw-leading,var(--vui-line-slot-sm))] font-semibold text-[var(--fg-primary)]",
  name: "break-words text-vui-xs [line-height:var(--vui-line-readable)] font-normal text-[var(--fg-secondary)]",
  action: "min-h-11 w-full",
  fields: "flex min-w-0 flex-col gap-3 rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3",
  field: "flex min-w-0 flex-col gap-1.5 text-vui-xs [line-height:var(--vui-line-readable)] text-[var(--fg-secondary)]",
  select: "min-h-11 w-full min-w-0",
  hint: "break-words text-vui-xs [line-height:var(--vui-line-readable)] text-[var(--fg-secondary)]",
  error: "break-words text-vui-xs [line-height:var(--vui-line-readable)] text-[var(--fg-danger,crimson)]",
} as const;
