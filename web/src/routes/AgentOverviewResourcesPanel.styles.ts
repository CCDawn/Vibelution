const styles = {
  section: "min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_54%,transparent)] p-3",
  header: "flex items-center justify-between gap-2",
  title: "m-0 text-sm font-semibold text-[var(--fg-primary)]",
  list: "mt-2 grid gap-1.5",
  item: "grid min-w-0 grid-cols-[minmax(0,_1fr)_auto] items-center gap-2 rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--vui-surface-base)_52%,transparent)] px-2 py-1.5",
  itemText: "min-w-0 [&_span]:block [&_span]:text-[11px] [&_span]:font-medium [&_span]:text-[var(--fg-tertiary)] [&_strong]:block [&_strong]:truncate [&_strong]:text-xs [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)]",
  empty: "m-0 mt-2 text-xs leading-5 text-[var(--fg-secondary)]",
} as const;

export default styles;
