export const statusTone: Record<string, string> = {
  qualified: "border-[color-mix(in_srgb,var(--state-success)_30%,transparent)] bg-[var(--vui-status-success-bg)] text-[var(--vui-status-success-fg)]",
  unsupported: "border-[color-mix(in_srgb,var(--state-warning)_30%,transparent)] bg-[var(--vui-status-warning-bg)] text-[var(--vui-status-warning-fg)]",
  rejected: "border-[color-mix(in_srgb,var(--state-error)_30%,transparent)] bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)]",
  not_established: "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]",
};

const styles = {
  evidenceList: "grid min-w-0 gap-1",
  evidenceLabel: "text-[var(--fg-secondary)]",
  evidenceItems: "grid min-w-0 gap-1",
  evidenceItem: "grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] gap-2",
  evidenceType: "text-[var(--fg-tertiary)]",
  evidenceId: "min-w-0 break-all text-[var(--fg-primary)]",
  emptyText: "text-[var(--fg-tertiary)]",
  tagList: "flex min-w-0 flex-wrap gap-1",
  content: "grid min-w-0 gap-3",
  statusList: "flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-[var(--fg-secondary)]",
  variableContract:
    "grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-muted)] p-2",
  variableTag: "max-w-full break-all rounded bg-[var(--vui-control-muted)] px-1.5 py-0.5",
  frozenControls: "grid min-w-0 gap-1",
  frozenControl: "max-w-full break-words rounded border border-[var(--vui-border-subtle)] px-1.5 py-0.5",
  claimList: "grid min-w-0 gap-2",
  claimDetails:
    "group min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  claimSummary: "grid cursor-pointer min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-start gap-2",
  statusBadge: "rounded border px-1.5 py-0.5",
  claimTitle: "min-w-0 break-words font-semibold text-[var(--fg-primary)]",
  claimBody: "mt-2 grid min-w-0 gap-3 border-t border-[var(--vui-border-subtle)] pt-2",
  evidenceGrid: "grid min-w-0 gap-2 md:grid-cols-2",
  breakWords: "max-w-full break-words",
  breakAll: "max-w-full break-all",
  compactDetails:
    "group min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-2 py-1.5 [font-size:var(--vui-font-xs)]",
  compactSummary: "cursor-pointer select-none font-semibold text-[var(--fg-secondary)]",
  compactBody: "mt-2 grid min-w-0 gap-2 border-t border-[var(--vui-border-subtle)] pt-2",
  previewClaim: "min-w-0 break-words text-[var(--fg-primary)]",
  detailSection:
    "grid min-w-0 gap-3 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3 [font-size:var(--vui-font-sm)]",
  detailHeader: "grid min-w-0 gap-1",
} as const;

export default styles;
