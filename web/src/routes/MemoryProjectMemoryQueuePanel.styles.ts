import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  copyNotice: `copyNotice min-w-0 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]`,
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  filterButton:
    "filterButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  filterButtonActive:
    "filterButtonActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  panelError: `panelError min-w-0 ${vuiFlatPanelClass} p-2 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  projectMemoryProposalActions:
    "projectMemoryProposalActions min-w-0 flex flex-wrap items-center gap-1.5",
  projectMemoryProposalFiles:
    "projectMemoryProposalFiles min-w-0",
  projectMemoryProposalList:
    "projectMemoryProposalList min-w-0 grid min-h-0 content-start gap-1.5 overflow-y-auto overflow-x-hidden",
  projectMemoryProposalMain:
    "projectMemoryProposalMain min-w-0",
  projectMemoryProposalMeta:
    "projectMemoryProposalMeta min-w-0 flex flex-wrap items-center gap-1.5",
  projectMemoryProposalNote:
    "projectMemoryProposalNote min-w-0",
  projectMemoryProposalResolved:
    "projectMemoryProposalResolved min-w-0",
  projectMemoryProposalRow: `projectMemoryProposalRow min-w-0 ${vuiOpaqueRowClass} p-2`,
  projectMemoryProposalTitleLine: `projectMemoryProposalTitleLine min-w-0 ${vuiOpaqueRowClass} p-2 [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)] !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5`,
  projectMemoryQueueControls:
    "projectMemoryQueueControls min-w-0 flex flex-wrap items-center gap-1.5",
  projectMemoryQueuePanel: `projectMemoryQueuePanel relative z-[1] min-w-0 ${vuiFlatPanelClass} p-2 grid min-h-0 max-h-[min(220px,28vh)] grid-rows-[auto_auto_minmax(0,1fr)] content-start gap-1.5 overflow-hidden`,
  projectMemoryQueueStats:
    "projectMemoryQueueStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] min-h-0 content-start gap-1.5",
} as const;

export default styles;
