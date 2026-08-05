import {
  vuiOpaqueRowClass,
  vuiStateDangerSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  workflowGraphCanvas:
    "workflowGraphCanvas min-w-[var(--workflow-graph-width,720px)] grid min-h-0 gap-2 p-2 relative h-full w-full",
  workflowGraphEdge:
    "workflowGraphEdge min-w-0 fill-none stroke-[color-mix(in_srgb,var(--fg-tertiary)_55%,transparent)] [stroke-width:1.25]",
  workflowGraphEdgeMuted:
    "workflowGraphEdgeMuted min-w-0 fill-none stroke-[color-mix(in_srgb,var(--fg-tertiary)_22%,transparent)] [stroke-width:1] [stroke-opacity:0.55]",
  workflowGraphEdgeFocus:
    "workflowGraphEdgeFocus min-w-0 fill-none stroke-[color-mix(in_srgb,var(--accent-cool)_78%,var(--fg-secondary))] [stroke-width:2] [stroke-opacity:0.95]",
  workflowGraphMarkerFill:
    "workflowGraphMarkerFill fill-[color-mix(in_srgb,var(--accent-cool)_78%,var(--fg-secondary))]",
  workflowGraphMarkerFillMuted:
    "workflowGraphMarkerFillMuted fill-[color-mix(in_srgb,var(--fg-tertiary)_35%,transparent)]",
  workflowGraphFrame:
    "workflowGraphFrame min-w-0 h-[var(--workflow-graph-height,360px)] min-h-[var(--workflow-graph-height,360px)] w-[var(--workflow-graph-width,720px)] max-w-full overflow-auto [scrollbar-gutter:stable]",
  workflowGraphHint:
    "workflowGraphHint m-0 mb-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-1.5 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)]",
  workflowGraphNode: `workflowGraphNode min-w-0 absolute left-[var(--workflow-graph-node-x,0px)] top-[var(--workflow-graph-node-y,0px)] grid h-[58px] w-[168px] content-center gap-0.5 overflow-hidden ${vuiOpaqueRowClass} px-2 py-1 text-left [font-size:var(--vui-font-xs)] leading-tight shadow-none cursor-pointer [&_span]:truncate [&_strong]:truncate focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)]`,
  workflowGraphNodeDanger:
    `workflowGraphNodeDanger min-w-0 ${vuiStateDangerSoftClass}`,
  workflowGraphNodeNeutral:
    "workflowGraphNodeNeutral min-w-0",
  workflowGraphNodeReady:
    "workflowGraphNodeReady min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  workflowGraphNodeWarning:
    "workflowGraphNodeWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  workflowGraphNodeFocus:
    "workflowGraphNodeFocus min-w-0 z-[2] ring-2 ring-[color-mix(in_srgb,var(--accent-cool)_55%,transparent)] shadow-[0_0_0_1px_color-mix(in_srgb,var(--accent-cool)_25%,transparent)]",
  workflowGraphNodeDim:
    "workflowGraphNodeDim min-w-0 opacity-45",
  workflowGraphSvg:
    "workflowGraphSvg min-w-0 absolute inset-0 h-full w-full overflow-visible pointer-events-none",
} as const;

export default styles;
