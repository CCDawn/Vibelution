export default {
  root: "grid w-full min-w-0 !flex-nowrap grid-cols-[minmax(12rem,1fr)_auto_max-content] items-center gap-x-3 overflow-x-auto",
  switcher: "min-w-0 w-full [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  empty: "block min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  status: "flex shrink-0 items-center gap-2 whitespace-nowrap min-w-[8.75rem] px-0.5",
  statusLabel: "[font-size:var(--vui-font-2xs)] font-bold tracking-wide text-[var(--fg-tertiary)]",
  statusEmpty: "[font-size:var(--vui-font-sm)] text-[var(--fg-tertiary)]",
  actions: "flex flex-nowrap items-center justify-self-end gap-2",
  nav: "!flex-nowrap",
} as const;
