const styles: Record<string, string> = {
  root:
    "min-w-0 rounded-[var(--vui-radius-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2.5 shadow-[var(--vui-shadow-soft)]",
  projectWarning:
    "mb-3 flex items-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[var(--vui-status-warning-bg)] px-2.5 py-2 [font-size:var(--vui-font-2xs)] text-[var(--state-warning)]",
  error:
    "mb-3 rounded-lg border border-[color-mix(in_srgb,var(--state-error)_35%,var(--vui-border-subtle))] bg-[var(--vui-status-danger-bg)] px-2.5 py-2 [font-size:var(--vui-font-2xs)] text-[var(--state-error)]",
  grid: "grid grid-cols-2 gap-2.5",
  card:
    "flex min-w-0 items-center justify-between gap-3 rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-inset)] px-3 py-2.5",
  role:
    "inline-flex min-w-0 items-center gap-1.5 [font-size:var(--vui-font-2xs)] font-bold text-[var(--fg-primary)]",
  controls: "flex shrink-0 items-center gap-2",
  status: "px-2 py-0.5 text-[10px] font-medium",
  actions: "flex items-center gap-1.5",
};

export default styles;
