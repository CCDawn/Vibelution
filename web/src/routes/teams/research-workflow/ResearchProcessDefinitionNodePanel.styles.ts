const styles = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  stage: "text-vui-micro-10 uppercase tracking-wide text-[var(--fg-tertiary)]",
  title: "m-0 [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  description: "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
} as const;

export default styles;
