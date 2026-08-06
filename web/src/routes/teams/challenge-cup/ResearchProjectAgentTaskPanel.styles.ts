const styles: Record<string, string> = {
  root:
    "min-w-0 rounded-[10px] border border-[var(--line)] bg-[var(--panel)] p-2.5 shadow-[var(--shadow)]",
  projectWarning:
    "mb-3 flex items-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--warning)_35%,var(--line))] bg-[var(--warning-soft)] px-2.5 py-2 text-[11px] text-[var(--warning)]",
  error:
    "mb-3 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,var(--line))] bg-[var(--danger-soft)] px-2.5 py-2 text-[11px] text-[var(--danger)]",
  grid: "grid grid-cols-2 gap-2.5",
  card:
    "flex min-w-0 items-center justify-between gap-3 rounded-lg border border-[var(--line)] bg-[var(--panel-subtle)] px-3 py-2.5",
  role:
    "inline-flex min-w-0 items-center gap-1.5 text-xs font-bold text-[var(--text)]",
  controls: "flex shrink-0 items-center gap-2",
  status: "px-2 py-0.5 text-[10px] font-medium",
  actions: "flex items-center gap-1.5",
};

export default styles;
