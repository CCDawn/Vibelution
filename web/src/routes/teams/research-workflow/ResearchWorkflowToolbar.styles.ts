export default {
  root: "flex w-full min-w-0 flex-col flex-nowrap items-stretch gap-2 overflow-hidden xl:flex-row xl:items-center xl:gap-x-3",
  context: "flex w-full min-w-0 items-center gap-2 overflow-x-auto overflow-y-hidden xl:flex-1 xl:overflow-hidden",
  leading:
    "w-[min(18rem,70vw)] min-w-[10rem] shrink-0 xl:w-[min(18rem,36%)] xl:min-w-0 [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  switcher:
    "w-[min(20rem,70vw)] min-w-[10rem] shrink-0 xl:min-w-0 xl:flex-1 xl:basis-[10rem] xl:max-w-[24rem] [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  empty: "block min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  actions: "flex w-full min-w-0 items-center gap-2 overflow-x-auto overflow-y-hidden xl:ms-auto xl:w-auto xl:shrink-0 xl:justify-end",
  trailing: "min-w-0 max-w-[16rem] shrink-0",
} as const;
