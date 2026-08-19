export default {
  root: "grid w-full min-w-0 !flex-nowrap grid-cols-[minmax(10rem,1fr)_max-content] items-center gap-x-3 gap-y-2 md:grid-cols-[minmax(12rem,1fr)_auto_max-content]",
  switcher: "min-w-0 w-full [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  empty: "block min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  phase: "shrink-0 whitespace-nowrap [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  actions: "col-span-2 flex min-w-0 flex-nowrap items-center justify-self-end gap-2 md:col-span-1",
  details: "w-[8.75rem] shrink-0",
} as const;
