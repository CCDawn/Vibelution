const styles = {
  root:
    "vui-routes-chatpromptassemblyinspector min-w-0 shrink-0 overflow-hidden text-[var(--fg-secondary)]",
  summary:
    "grid min-w-0 cursor-pointer list-none grid-cols-1 gap-1 py-1 text-left marker:hidden [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  titleGroup: "flex min-w-0 items-center gap-2",
  title:
    "m-0 truncate [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  summaryMeta:
    "min-w-0 truncate [font-size:var(--vui-font-xs)] tabular-nums text-[var(--fg-tertiary)]",
  chevron:
    "h-3.5 w-3.5 shrink-0 text-[var(--fg-tertiary)] transition-transform duration-150 group-open:rotate-90",
  body:
    "grid gap-2 border-t border-[var(--vui-border-subtle)] pt-2 [font-size:var(--vui-font-xs)]",
  facts: "grid gap-1",
  fact:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-2 rounded-[var(--vui-radius-sm)] bg-[var(--vui-surface-row)] px-2 py-1.5",
  label: "text-[var(--fg-tertiary)]",
  value: "min-w-0 truncate font-medium text-[var(--fg-primary)]",
  legacy:
    "m-0 leading-relaxed text-[var(--fg-secondary)]",
  segmentList: "grid gap-1",
  segment:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-x-2 gap-y-0.5 rounded-[var(--vui-radius-sm)] border border-[var(--vui-border-subtle)] px-2 py-1.5",
  segmentIdentity: "min-w-0 truncate font-medium text-[var(--fg-primary)]",
  tier: "col-span-2 min-w-0 truncate text-[var(--fg-tertiary)]",
  decision:
    "rounded-full border border-[var(--vui-border-subtle)] px-1.5 py-0.5 font-medium text-[var(--fg-secondary)]",
} as const;

export default styles;
