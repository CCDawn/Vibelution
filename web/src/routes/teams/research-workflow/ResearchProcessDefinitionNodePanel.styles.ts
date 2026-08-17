const styles = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  stage: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  title: "m-0 text-base font-semibold text-[var(--fg-primary)]",
  description: "m-0 text-sm text-[var(--fg-secondary)]",
} as const;

export default styles;
