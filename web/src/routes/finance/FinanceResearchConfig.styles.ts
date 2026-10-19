export default {
  surface: "w-full max-w-4xl border border-[var(--vui-border-subtle)] rounded-lg @container/research-config",
  heading: "flex items-center justify-between gap-3 mb-4",
  title: "flex items-center gap-2 text-sm",
  caption: "text-xs text-[var(--fg-tertiary)]",
  fields: "grid grid-cols-1 @min-[480px]/research-config:grid-cols-2 items-start gap-4",
  footer: "mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--vui-border-subtle)] pt-4",
  field: "grid min-w-0 gap-1.5 text-xs text-[var(--fg-tertiary)]",
  modelStatus: "mt-3",
  modelStatusDetail: "ml-1",
} as const;
