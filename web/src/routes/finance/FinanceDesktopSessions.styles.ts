export default {
  root: "flex h-11 min-w-0 shrink-0 items-center gap-1 border-b border-vui-border-subtle px-2",
  scroll: "min-w-0 flex-1 overflow-x-auto",
  tabs: "!block w-max min-w-full",
  list: "!flex-nowrap !w-max !min-w-full !max-w-none !justify-start !border-0 !bg-transparent !p-0",
  trigger: "!max-w-52 !min-h-8 shrink-0 !text-vui-2xs whitespace-nowrap",
  label: "flex min-w-0 items-center gap-2 [&>span]:truncate",
  busy: "h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent-cool)]",
  actions: "flex shrink-0 items-center gap-0.5",
  icon: "!h-7 !min-h-7 !w-7 !min-w-7 !border-transparent !bg-transparent !px-0 !shadow-none",
} as const;
