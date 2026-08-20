export default {
  root: "flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-2",
  switcher: "min-w-0 flex-1 basis-[12rem] max-w-[20rem] md:max-w-[24rem] [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  empty: "block min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  phase: "min-w-0 shrink truncate [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  actions: "ms-auto flex shrink-0 flex-nowrap items-center gap-2",
  details: "w-[9.5rem] shrink-0",
} as const;
