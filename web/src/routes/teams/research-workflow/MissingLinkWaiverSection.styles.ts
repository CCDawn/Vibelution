/**
 * Shared missing-link waiver rows (缺陷⑪ surface, 缺陷⑰ shared extraction).
 * Semantic prefix: missingLinkWaiver — consumed by the source-collection graph
 * workspace panel and the workflow-canvas knowledge sideflow evidence tab.
 */
const styles = {
  missingLinkWaiverSection:
    "missingLinkWaiverSection min-w-0 grid gap-1.5",
  missingLinkWaiverMeta:
    "missingLinkWaiverMeta min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1",
  missingLinkWaiverRow:
    "missingLinkWaiverRow min-w-0 grid gap-1.5 rounded-[var(--radius-control)] border border-[color:var(--border-soft)] p-1.5 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-secondary)]",
  missingLinkWaiverPath:
    "missingLinkWaiverPath min-w-0 truncate text-[var(--fg-primary)]",
  missingLinkWaiverWaivedBadge:
    "missingLinkWaiverWaivedBadge shrink-0 rounded-[var(--radius-control)] border border-[color:var(--border-soft)] px-1.5 py-0.5 text-[var(--fg-tertiary)]",
  missingLinkWaiverWaiveButton:
    "missingLinkWaiverWaiveButton shrink-0",
  missingLinkWaiverEditor:
    "missingLinkWaiverEditor min-w-0 grid gap-1",
  missingLinkWaiverError:
    "missingLinkWaiverError text-[var(--fg-danger)]",
  missingLinkWaiverNotice:
    "missingLinkWaiverNotice text-[var(--fg-secondary)]",
  missingLinkWaiverHint:
    "missingLinkWaiverHint text-[var(--fg-tertiary)]",
} as const;

export default styles;
