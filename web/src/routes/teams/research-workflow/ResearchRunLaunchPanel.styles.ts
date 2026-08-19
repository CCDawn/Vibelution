export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  state: "m-3",
  selectedQuestion: "grid min-w-0 gap-1 border-vui-border-subtle",
  questionTitle: "truncate text-sm font-semibold text-vui-fg-primary",
  questionScope: "line-clamp-2 text-xs leading-relaxed text-vui-fg-secondary",
  selectedExperiment: "grid min-w-0 gap-1.5 border-vui-border-subtle",
  experimentHeader: "flex min-w-0 items-center justify-between gap-2",
  experimentTitle: "min-w-0 truncate text-sm font-semibold text-vui-fg-primary",
  experimentMeta: "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-vui-fg-secondary",
  experimentStatus: "text-xs font-medium text-vui-fg-primary",
  experimentBlockerText: "text-xs leading-relaxed text-[var(--state-warning)]",
  blockers: "grid min-w-0 list-disc gap-0.5 pl-4 text-xs leading-relaxed text-vui-fg-secondary",
  error: "text-sm text-[var(--state-error)]",
  techDetails:
    "grid max-w-full gap-1 text-xs text-[var(--vui-fg-secondary)] [&>summary]:w-fit [&>summary]:cursor-pointer [&_code]:wrap-anywhere [&_code]:text-[10px]",
  actions: "flex justify-end gap-2",
} as const;
