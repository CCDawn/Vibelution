export default {
  root: "flex min-w-0 flex-wrap items-center justify-between gap-2",
  context: "flex min-w-0 items-center gap-2 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  primary: "truncate text-[var(--fg-primary)]",
  truncated: "truncate",
  next: "truncate text-[var(--fg-primary)]",
  nextAction: "max-w-[16rem] truncate text-[var(--fg-primary)]",
  actions: "flex flex-wrap items-center gap-2",
  select: "min-w-[18rem] max-w-[28rem]",
} as const;
