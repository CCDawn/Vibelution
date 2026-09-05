export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  surface: "space-y-3 p-3 [font-size:var(--vui-font-xs)]",
  groups: "m-0 list-none space-y-3 p-0",
  groupTitle: "m-0 [font-size:var(--vui-font-2xs)] font-semibold text-[var(--fg-primary)]",
  items: "mt-1 list-none space-y-1 p-0",
  item: "flex min-w-0 flex-col gap-1 rounded border border-[var(--border-subtle)] px-2 py-1.5 [font-size:var(--vui-font-2xs)] [overflow-wrap:anywhere]",
  status: "text-[var(--fg-tertiary)]",
  empty: "h-auto w-full border-0 bg-transparent",
} as const;
