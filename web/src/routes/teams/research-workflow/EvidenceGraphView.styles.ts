const styles: Record<string, string> = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  emptyState: "h-auto w-full border-0 bg-transparent",
  alert:
    "rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]",
  headerRow: "flex items-center justify-between gap-2",
  sectionLabel: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  list: "m-0 list-none space-y-1 p-0",
  nodeItem: "rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs",
  nodeTitle: "font-medium break-all text-[var(--fg-primary)]",
  nodeMeta: "break-all text-[var(--fg-secondary)]",
  edgeItem:
    "rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs break-all text-[var(--fg-primary)]",
  emptyEdges: "m-0 text-xs text-[var(--fg-secondary)]",
  sectionGrid: "grid gap-1",
  fill: "h-full min-h-0",
};

export default styles;
