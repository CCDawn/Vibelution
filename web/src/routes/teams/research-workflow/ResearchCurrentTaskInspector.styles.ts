export default {
  root: "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] bg-[var(--surface-canvas)]",
  header: "border-b border-[var(--border-subtle)] bg-[var(--surface-panel)] px-4 py-3",
  titleRow: "flex min-w-0 items-start justify-between gap-3",
  title: "min-w-0 text-balance text-base font-semibold leading-6 text-[var(--fg-primary)]",
  detail: "px-4 pt-3 text-pretty [font-size:var(--vui-font-sm)] leading-5 text-[var(--fg-secondary)]",
  progress: "px-4 pt-2 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  body: "min-h-0 overflow-auto",
  empty: "flex h-full min-h-40 items-center justify-center px-5 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-tertiary)]",
  footer: "border-t border-[var(--border-subtle)] bg-[var(--surface-panel)] px-4 py-3 shadow-[0_-8px_18px_-16px_rgba(15,23,42,0.45)]",
  primaryAction: "w-full",
} as const;
