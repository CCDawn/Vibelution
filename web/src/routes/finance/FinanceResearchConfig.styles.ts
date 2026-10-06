export default {
  surface: "border border-[var(--vui-border-subtle)] rounded-lg",
  heading: "flex items-center justify-between gap-3 mb-4",
  title: "flex items-center gap-2 text-sm",
  caption: "text-xs text-[var(--fg-tertiary)]",
  fields: "grid grid-cols-[repeat(auto-fit,minmax(min(100%,11rem),1fr))] items-end gap-3",
  field: "grid min-w-0 gap-1.5 text-xs text-[var(--fg-tertiary)]",
  modelStatus: "mt-3",
  modelStatusDetail: "ml-1",
} as const;
