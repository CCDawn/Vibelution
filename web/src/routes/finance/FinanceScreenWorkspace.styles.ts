const border = "border-[var(--vui-border-subtle)]";

export default {
  root: "grid min-w-0 content-start gap-3",
  smartPanel: `grid min-w-0 rounded-[var(--vui-radius-soft)] border ${border} bg-[var(--vui-surface-panel)]`,
  form: "grid min-w-0 gap-3",
  criteriaLabel: "text-xs font-medium text-[var(--fg-secondary)]",
  criteriaInput: "min-w-0 w-full resize-y",
  examples: "flex min-w-0 flex-wrap gap-1.5",
  example: "!h-auto !min-h-0 !justify-start !px-2 !py-1 text-left text-xs",
  error: "m-0 text-xs text-[var(--state-warning)]",
  actions: "flex min-w-0 justify-end",
} as const;
