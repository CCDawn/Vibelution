export default {
  root: "flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-2",
  switcher: "min-w-0 w-full max-w-[20rem] md:w-auto md:min-w-[12rem] md:max-w-[24rem] [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  empty: "block min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  phase: "shrink-0 whitespace-nowrap [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  actions: "flex min-w-0 flex-nowrap items-center gap-2 md:ms-auto",
  details: "w-[8.75rem] shrink-0",
} as const;
