/** Missing-link waiver rows for the ingestion graph workspace (缺陷⑪). */
const styles = {
  graphMissingLinkSection:
    "graphMissingLinkSection min-w-0 grid gap-1.5",
  graphMissingLinkHeader:
    "graphMissingLinkHeader min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1",
  graphMissingLinkRow:
    "graphMissingLinkRow min-w-0 grid gap-1.5 rounded-[var(--radius-control)] border border-[color:var(--border-soft)] p-1.5 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-secondary)]",
  graphMissingLinkMeta:
    "graphMissingLinkMeta min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1",
  graphMissingLinkPath:
    "graphMissingLinkPath min-w-0 truncate text-[var(--fg-primary)]",
  graphMissingLinkWaivedBadge:
    "graphMissingLinkWaivedBadge shrink-0 rounded-[var(--radius-control)] border border-[color:var(--border-soft)] px-1.5 py-0.5 text-[var(--fg-tertiary)]",
  graphMissingLinkWaiveButton:
    "graphMissingLinkWaiveButton shrink-0",
  graphMissingLinkEditor:
    "graphMissingLinkEditor min-w-0 grid gap-1",
  graphMissingLinkError:
    "graphMissingLinkError text-[var(--fg-danger)]",
  graphMissingLinkNotice:
    "graphMissingLinkNotice text-[var(--fg-secondary)]",
  graphMissingLinkHint:
    "graphMissingLinkHint text-[var(--fg-tertiary)]",
} as const;

export default styles;
