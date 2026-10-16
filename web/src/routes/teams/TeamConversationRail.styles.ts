export default {
  root: "flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-auto",
  entries: "grid shrink-0 gap-1",
  heading: "px-2 text-vui-2xs text-[var(--fg-tertiary)]",
  entry: "h-auto! w-full justify-start px-2 py-2 aria-pressed:bg-[var(--vui-selection-bg)]",
  identity: "flex min-w-0 items-center gap-2.5 text-left",
  avatar: "grid h-7 w-7 shrink-0 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-base)] text-vui-2xs text-[var(--fg-secondary)]",
  copy: "min-w-0",
  name: "block truncate text-vui-micro-13 font-medium",
  role: "block truncate text-vui-2xs leading-5 text-[var(--fg-tertiary)]",
  navigation: "min-h-0 flex-1 border-t border-[var(--vui-border-subtle)] pt-2",
  recovery: "flex flex-wrap items-center justify-between gap-2 px-2 pb-2",
  recoveryHint: "text-vui-2xs text-[var(--fg-secondary)]",
} as const;
