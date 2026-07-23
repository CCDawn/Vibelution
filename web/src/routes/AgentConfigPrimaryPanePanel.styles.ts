const styles = {
  opsZone:
    "grid min-w-0 content-start gap-2 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-error)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_4%,var(--vui-surface-panel))] p-2.5",
  opsHeader: "grid min-w-0 gap-0.5 px-0.5",
  opsTitle:
    "m-0 [font-size:var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-[var(--state-error)]",
  opsHint:
    "m-0 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
} as const;

export default styles;
