const styles: Record<string, string> = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  headerRow: "flex items-center justify-between gap-2",
  sectionLabel: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  statGrid: "grid grid-cols-3 gap-2 text-xs",
  statCell: "rounded border border-[var(--border-subtle)] px-2 py-1.5",
  statLabel: "text-[var(--fg-tertiary)]",
  statValue: "text-lg font-semibold text-[var(--fg-primary)]",
  emptyState: "h-auto w-full border-0 bg-transparent",
  list: "m-0 list-none space-y-1 p-0",
  row: "flex items-center justify-between gap-2 rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs",
  rowMain: "min-w-0",
  nodeTitle: "font-medium break-all text-[var(--fg-primary)]",
  nodeMeta: "break-all text-[var(--fg-secondary)]",
  alert:
    "rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]",
  fill: "h-full min-h-0",
};

export default styles;
