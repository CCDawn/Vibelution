export default {
  root:
    "teamShellStatusRail flex h-full min-h-0 min-w-0 flex-1 flex-col gap-2.5 overflow-hidden",
  body: "grid min-h-0 flex-1 content-start gap-2.5 overflow-auto",
  nextCard: "grid gap-1.5",
  nextKicker:
    "[font-size:var(--vui-font-xs)] font-[700] tracking-[0.04em] text-[var(--fg-tertiary)]",
  nextTitle: "m-0 [font-size:var(--vui-font-sm)] font-[760] text-[var(--fg-primary)]",
  nextBody:
    "m-0 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  sectionLabel:
    "m-0 [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-primary)]",
  stageList: "grid gap-1.5",
  stageItem:
    "grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-transparent px-2 py-1.5",
  stageItemActive:
    "grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-1.5",
  stageTitle: "[font-size:var(--vui-font-sm)] font-[720] text-[var(--fg-primary)]",
  nodeIndex: "grid gap-1.5",
  nodeItem:
    "!grid h-auto w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-transparent px-2 py-1.5 text-left !whitespace-normal",
  nodeItemActive:
    "!grid h-auto w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-1.5 text-left !whitespace-normal",
  nodeAgent: "col-span-2 min-w-0 truncate [font-size:var(--vui-font-2xs)] text-[var(--fg-tertiary)]",
} as const;
