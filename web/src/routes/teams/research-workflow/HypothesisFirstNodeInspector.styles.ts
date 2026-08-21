const styles = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  stage: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  title: "m-0 [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  description: "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  facts: "flex flex-col gap-1.5",
  factLabel: "text-[var(--fg-tertiary)]",
  envelope: "m-0 whitespace-pre-wrap break-all [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  actions:
    "sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-1 py-3 shadow-[0_-10px_20px_-18px_rgba(15,23,42,0.55)]",
  secondary: "mt-auto flex flex-wrap items-center gap-2 pt-2",
  status: "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  commandWrap: "flex flex-col items-start gap-1",
  commandDetail: "[font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  stageSummary: "flex flex-col gap-1 rounded-[var(--vui-radius-sm)] border border-[color:var(--vui-border-subtle)] bg-[color:var(--vui-surface-raised)] p-3",
  task: "flex min-h-0 flex-col gap-3",
  fill: "h-full",
} as const;

export default styles;
