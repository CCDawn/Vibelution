export default {
  surface: "min-w-0 border border-[var(--vui-border-subtle)] rounded-lg",
  heading: "flex items-center justify-between gap-4 mb-3",
  titleRow: "flex items-center gap-4",
  title: "text-sm",
  adjustment: "text-xs text-[var(--fg-tertiary)]",
  legend: "flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums text-[var(--fg-secondary)] min-h-6",
  shortAverage: "text-[var(--state-warning)]",
  longAverage: "text-[var(--accent-cool)]",
  chart: "w-full h-auto max-h-[330px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)]",
  footer: "flex justify-between text-xs text-[var(--fg-tertiary)]",
} as const;
