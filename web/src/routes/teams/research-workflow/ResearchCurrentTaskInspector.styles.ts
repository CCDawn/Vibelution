export default {
  root: "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto]",
  header: "border-b border-[var(--border-subtle)] px-2 py-3",
  titleRow: "flex min-w-0 items-center justify-between gap-3",
  title: "min-w-0 text-balance text-vui-md font-semibold leading-6 text-[var(--fg-primary)]",
  detail: "text-pretty [font-size:var(--vui-font-sm)] leading-5 text-[var(--fg-secondary)]",
  errorSteps: "mt-2 list-disc space-y-1 pl-4 [overflow-wrap:anywhere]",
  progress: "[font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  body: "flex min-h-0 min-w-0 flex-col gap-4 overflow-auto overflow-x-hidden px-2 py-4 [&>*]:shrink-0",
  empty: "flex h-full min-h-40 items-center justify-center px-5 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-tertiary)]",
  footer: "empty:hidden border-t border-[var(--border-subtle)] px-2 py-3 shadow-none",
  primaryAction: "w-full",
} as const;
