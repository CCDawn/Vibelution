export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3 [font-size:var(--vui-font-xs)]",
  details: "m-0 grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 [font-size:var(--vui-font-2xs)]",
  label: "text-[var(--fg-tertiary)]",
  value: "m-0",
  valueBreak: "m-0 break-all",
  sectionTitle: "m-0 [font-size:var(--vui-font-2xs)] font-semibold",
  blockers: "mt-1 list-none space-y-1 p-0 [font-size:var(--vui-font-2xs)]",
  blocker: "flex justify-between gap-2 rounded border border-[var(--border-subtle)] px-2 py-1.5",
  owner: "truncate text-[var(--fg-secondary)]",
  roomMissing: "rounded border border-[var(--border-subtle)] px-2 py-1.5 [font-size:var(--vui-font-2xs)]",
} as const;
