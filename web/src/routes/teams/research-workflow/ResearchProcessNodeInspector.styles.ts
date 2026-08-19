export default {
  centered: "flex h-full min-h-0 flex-col items-stretch justify-center p-3",
  empty: "h-auto w-full border-0 bg-transparent",
  root: "flex h-full min-h-0 flex-col gap-4 overflow-auto p-3",
  stage: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  title: "m-0 [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  meta: "mt-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  status: "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  nav: "flex flex-wrap items-center gap-2",
} as const;
