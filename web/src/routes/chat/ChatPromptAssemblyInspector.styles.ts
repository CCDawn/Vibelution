const styles = {
  root:
    "vui-routes-chatpromptassemblyinspector mx-3 mt-2 shrink-0 overflow-hidden rounded-[var(--vui-radius-md)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]",
  summary:
    "grid cursor-pointer list-none grid-cols-[minmax(0,1fr)_max-content] items-center gap-3 px-3 py-2 marker:hidden [&::-webkit-details-marker]:hidden",
  titleGroup: "flex min-w-0 items-center gap-2",
  title:
    "m-0 truncate [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  summaryMeta:
    "shrink-0 [font-size:var(--vui-font-xs)] tabular-nums text-[var(--fg-tertiary)]",
  chevron:
    "h-3.5 w-3.5 shrink-0 text-[var(--fg-tertiary)] transition-transform duration-150 group-open:rotate-90",
  body:
    "grid gap-2 border-t border-[var(--vui-border-subtle)] px-3 py-2.5 [font-size:var(--vui-font-xs)]",
  facts: "grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2",
  fact:
    "grid min-w-0 gap-0.5 rounded-[var(--vui-radius-sm)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-base)] px-2 py-1.5",
  label: "text-[var(--fg-tertiary)]",
  value: "min-w-0 truncate font-medium text-[var(--fg-primary)]",
  legacy:
    "m-0 leading-relaxed text-[var(--fg-secondary)]",
  segmentList: "grid gap-1",
  segment:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_max-content_max-content] items-center gap-2 rounded-[var(--vui-radius-sm)] border border-[var(--vui-border-subtle)] px-2 py-1.5 max-[620px]:grid-cols-[minmax(0,1fr)_max-content] max-[620px]:[&>span:nth-child(2)]:hidden",
  segmentIdentity: "min-w-0 truncate font-medium text-[var(--fg-primary)]",
  tier: "truncate text-[var(--fg-tertiary)]",
  decision:
    "rounded-full border border-[var(--vui-border-subtle)] px-1.5 py-0.5 font-medium text-[var(--fg-secondary)]",
} as const;

export default styles;
