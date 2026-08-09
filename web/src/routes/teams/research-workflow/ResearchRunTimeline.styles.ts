export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  surface: "space-y-3 p-3 text-sm",
  groups: "m-0 list-none space-y-3 p-0",
  groupTitle: "m-0 text-xs font-semibold text-[var(--fg-primary)]",
  items: "mt-1 list-none space-y-1 p-0",
  item: "flex items-center justify-between gap-3 rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs",
  status: "shrink-0 text-[var(--fg-tertiary)]",
  empty: "h-auto w-full border-0 bg-transparent",
} as const;
