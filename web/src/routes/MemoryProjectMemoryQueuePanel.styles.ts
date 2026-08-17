import {
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateDangerSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  copyNotice: `copyNotice min-w-0 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  queueFilterTabs: "queueFilterTabs inline-grid w-fit max-w-full min-w-0 gap-0",
  queueFilterTabsList:
    "queueFilterTabsList inline-flex min-w-0 max-w-full flex-wrap items-center gap-1 border-0 bg-transparent p-0",
  queueFilterTabsTrigger:
    `queueFilterTabsTrigger min-w-0 ${vuiControlQuietClass} ` +
    "data-[state=active]:border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] " +
    "data-[state=active]:bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] " +
    "data-[state=active]:text-[var(--accent-cool)]",
  panelError: `panelError min-w-0 ${vuiFlatPanelClass} p-2 ${vuiStateDangerSoftClass}`,
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
  projectMemoryProposalTitleLine: "projectMemoryProposalTitleLine min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5 [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)] [&_strong]:min-w-0 [&_strong]:truncate",
  projectMemoryQueueControls:
    "projectMemoryQueueControls min-w-0 flex flex-wrap items-center gap-1.5",
  // Wave 6D: height comes from usePersistedPaneHeight (project-memory-queue), not fixed max-h.
  projectMemoryQueuePanel: `projectMemoryQueuePanel relative z-[1] min-w-0 ${vuiFlatPanelClass} p-2 grid min-h-0 h-full grid-rows-[auto_auto_minmax(0,1fr)] content-start gap-1.5 overflow-hidden`,
  // PaneHeightResizeHandle owns row-resize visual; placement only.
  projectMemoryQueueResizeHandle:
    "projectMemoryQueueResizeHandle",
  projectMemoryQueueStats:
    "projectMemoryQueueStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] min-h-0 content-start gap-1.5",
} as const;

export default styles;
