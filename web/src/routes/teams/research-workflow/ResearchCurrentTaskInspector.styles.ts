export default {
  root: "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] bg-[var(--surface-canvas)]",
  header: "border-b border-[var(--border-subtle)] bg-[var(--surface-panel)] px-4 py-3",
  eyebrow: "mb-2 [font-size:var(--vui-font-2xs)] font-semibold uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  titleRow: "flex min-w-0 items-start justify-between gap-3",
  title: "min-w-0 text-balance text-base font-semibold leading-6 text-[var(--fg-primary)]",
  detail: "mt-2 text-pretty [font-size:var(--vui-font-sm)] leading-5 text-[var(--fg-secondary)]",
  progress: "mt-2 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  historyNotice: "mt-3 flex items-center justify-between gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-subtle)] p-2.5",
  historyCopy: "min-w-0 [font-size:var(--vui-font-xs)] leading-4 text-[var(--fg-secondary)]",
  body: "min-h-0 overflow-auto",
  empty: "flex h-full min-h-40 items-center justify-center px-5 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-tertiary)]",
  footer: "border-t border-[var(--border-subtle)] bg-[var(--surface-panel)] px-4 py-3 shadow-[0_-8px_18px_-16px_rgba(15,23,42,0.45)]",
} as const;
