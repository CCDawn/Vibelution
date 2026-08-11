export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  state: "m-3",
  selectedQuestion: "grid min-w-0 gap-1 border-vui-border-subtle",
  questionTitle: "truncate text-sm font-semibold text-vui-fg-primary",
  questionScope: "line-clamp-2 text-xs leading-relaxed text-vui-fg-secondary",
  error: "text-sm text-[var(--state-error)]",
  actions: "flex justify-end gap-2",
} as const;
