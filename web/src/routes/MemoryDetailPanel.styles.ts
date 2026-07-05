const styles = {
  copyNotice:
    "copyNotice min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  detailActions:
    "detailActions min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
  detailHeader:
    "detailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  detailPanel:
    "detailPanel min-w-0 min-h-0 overflow-auto rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  emptyDetail:
    "emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  factGrid:
    "factGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  generatedAt:
    "generatedAt min-w-0",
  impactPanel:
    "impactPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  manageDetailPanel:
    "manageDetailPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  panelEyebrow:
    "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  rawPanel:
    "rawPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  sectionPanel:
    "sectionPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  statusPill:
    "statusPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  statusPillMuted:
    "statusPillMuted min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  statusPillPrompt:
    "statusPillPrompt min-w-0",
  statusPillVisible:
    "statusPillVisible min-w-0",
  usageList:
    "usageList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  visibilityHeader:
    "visibilityHeader min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[22px_minmax(0,1fr)] items-start gap-2",
  visibilityPanel:
    "visibilityPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
} as const;

export default styles;
