export default {
  root: "rounded border border-[var(--border-subtle)] p-2 [font-size:var(--vui-font-2xs)]",
  head: "flex items-center justify-between gap-2",
  title: "m-0 font-semibold",
  detail: "m-0 mt-1 text-[var(--fg-secondary)]",
  preview: "mt-1 grid grid-cols-[64px_1fr] gap-x-2 gap-y-1",
  label: "text-[var(--fg-tertiary)]",
  value: "m-0",
  cards: "mt-2 flex flex-wrap gap-1",
  card: "rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-medium",
  packageLine: "m-0 mt-2 break-all text-[var(--fg-secondary)]",
  actions: "mt-2 flex flex-wrap items-center gap-2",
  gateNote: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-tertiary)]",
} as const;
