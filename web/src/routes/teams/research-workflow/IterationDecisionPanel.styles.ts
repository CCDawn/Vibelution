const styles: Record<string, string> = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  notice:
    "rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]",
  formGrid: "grid gap-2",
  fieldLabel: "grid gap-1 text-xs text-[var(--fg-secondary)]",
  list: "m-0 list-none space-y-1 p-0",
  listItem: "rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs",
  listItemTitle: "font-medium text-[var(--fg-primary)]",
  listItemMeta: "break-all text-[var(--fg-secondary)]",
  sectionLabel: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  emptyText: "m-0 text-xs text-[var(--fg-secondary)]",
  sectionGrid: "grid gap-1",
  emptyState: "h-auto w-full border-0 bg-transparent",
  autoHeight: "h-auto",
};

export default styles;
