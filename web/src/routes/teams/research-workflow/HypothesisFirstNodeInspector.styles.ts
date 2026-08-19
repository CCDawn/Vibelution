const styles = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  stage: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  title: "m-0 [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  description: "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  facts: "flex flex-col gap-1.5",
  factLabel: "text-[var(--fg-tertiary)]",
  envelope: "m-0 max-h-32 overflow-auto whitespace-pre-wrap break-all [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  actions: "mt-auto pt-2",
  fill: "h-full",
} as const;

export default styles;
