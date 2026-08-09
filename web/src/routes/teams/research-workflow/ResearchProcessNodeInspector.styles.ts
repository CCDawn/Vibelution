export default {
  centered: "flex h-full min-h-0 flex-col items-stretch justify-center p-3",
  empty: "h-auto w-full border-0 bg-transparent",
  root: "flex h-full min-h-0 flex-col gap-4 overflow-auto p-3",
  stage: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  title: "m-0 text-base font-semibold text-[var(--fg-primary)]",
  meta: "mt-1 text-xs text-[var(--fg-secondary)]",
} as const;
