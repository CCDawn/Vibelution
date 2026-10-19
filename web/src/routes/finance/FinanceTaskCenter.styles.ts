export default {
  page: "grid min-w-0 content-start gap-5",
  toolbar: "flex items-center justify-between gap-3",
  heading: "m-0 text-lg font-semibold",
  metrics: "grid min-w-0 gap-3 sm:grid-cols-3",
  metric: "grid gap-2 text-xs text-[var(--fg-tertiary)] [&>strong]:text-2xl [&>strong]:font-medium [&>strong]:text-[var(--fg-primary)]",
  list: "grid min-w-0 gap-2",
  row: "flex min-w-0 flex-wrap items-center gap-3 !border !border-[var(--vui-border-subtle)]",
  selected: "!border-[var(--accent-cool)]",
  identity: "grid min-w-0 flex-1 gap-2",
  title: "truncate text-sm",
  small: "text-xs text-[var(--fg-tertiary)]",
} as const;
