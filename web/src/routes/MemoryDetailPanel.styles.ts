import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  copyNotice: `copyNotice min-w-0 inline-flex w-fit max-w-full items-center gap-1.5 ${vuiOpaqueRowClass} p-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&>span]:min-w-0 [&>span]:break-words`,
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  detailActions: `detailActions min-w-0 flex w-fit max-w-full flex-wrap items-center gap-1.5 ${vuiOpaqueRowClass} p-1.5`,
  detailHeader:
    "detailHeader min-w-0 flex flex-wrap items-start justify-between gap-2 px-1 py-0.5 [&>div]:min-w-0 [&_h2]:min-w-0 [&_h2]:break-words [&_p]:min-w-0 [&_p]:line-clamp-2 [&_p]:break-words",
  detailPanel: `detailPanel min-w-0 min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  emptyDetail:
    "emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  factGrid:
    "factGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))] [&_section]:min-w-0 [&_section]:rounded-[var(--radius-control)] [&_section]:border [&_section]:border-[var(--vui-border-subtle)] [&_section]:bg-[var(--vui-surface-row)] [&_section]:p-2 [&_strong]:min-w-0 [&_strong]:break-all",
  generatedAt:
    "generatedAt min-w-0",
  impactPanel: `impactPanel min-w-0 ${vuiFlatPanelClass} p-2 [&>p]:min-w-0 [&>p]:break-words`,
  manageDetailPanel:
    "manageDetailPanel min-w-0 bg-[var(--vui-surface-panel)]",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  rawPanel: `rawPanel min-w-0 ${vuiFlatPanelClass} p-2 [&_pre]:max-w-full [&_pre]:whitespace-pre-wrap [&_pre]:break-words`,
  sectionPanel: `sectionPanel min-w-0 ${vuiFlatPanelClass} p-2 [&>p]:min-w-0 [&>p]:break-words`,
  statusPill:
    "statusPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  statusPillPrompt:
    "statusPillPrompt min-w-0",
  statusPillVisible:
    "statusPillVisible min-w-0",
  usageList:
    "usageList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  visibilityHeader:
    "visibilityHeader min-w-0 !grid grid-cols-[22px_minmax(0,1fr)] items-start gap-2 [&_div]:min-w-0 [&_p]:min-w-0 [&_p]:break-words",
  visibilityPanel: `visibilityPanel min-w-0 ${vuiFlatPanelClass} p-2`,
} as const;

export default styles;
