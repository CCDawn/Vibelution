const border = "border-[var(--vui-border-subtle)]";

export default {
  root: "mx-auto grid w-full min-w-0 max-w-4xl content-start gap-5",
  smartPanel: `grid min-w-0 rounded-vui-soft border ${border} bg-[var(--vui-surface-panel)]`,
  form: "grid min-w-0 content-start gap-5",
  criteriaLabel: "text-xs font-medium text-[var(--fg-secondary)]",
  criteriaInput: "min-w-0 w-full !h-auto !min-h-24 resize-y",
  examples: "flex min-w-0 flex-wrap gap-2",
  example: "!h-auto !min-h-0 !justify-start !px-2 !py-1 text-left text-xs",
  error: "m-0 text-xs text-[var(--state-warning)]",
  actions: "flex min-w-0 justify-end",
} as const;
