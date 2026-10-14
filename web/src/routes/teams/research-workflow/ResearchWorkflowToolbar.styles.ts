export default {
  questionTrigger: "max-w-full truncate",
  root: "flex w-max min-w-0 flex-row flex-nowrap items-center gap-x-3",
  context: "flex min-w-0 shrink-0 items-center gap-2",
  leading:
    "w-[min(18rem,70vw)] min-w-[10rem] shrink-0 xl:w-[min(18rem,36%)] xl:min-w-0 [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  switcher:
    "w-[min(20rem,70vw)] min-w-[10rem] shrink-0 xl:min-w-0 xl:flex-1 xl:basis-[10rem] xl:max-w-[24rem] [&_[data-vui=select-shell]]:w-full [&_[data-vui=select-shell]]:min-w-0 [&_[data-vui=select]]:w-full [&_[data-vui=select]]:min-w-0",
  empty: "block min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  actions: "flex min-w-0 shrink-0 items-center gap-2",
  trailing: "min-w-0 max-w-[16rem] shrink-0",
} as const;
