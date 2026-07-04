const styles = {
  workflowGraphCanvas:
    "workflowGraphCanvas min-w-0 grid min-h-0 gap-2 p-2 relative h-full w-full",
  workflowGraphEdge:
    "workflowGraphEdge min-w-0",
  workflowGraphFrame:
    "workflowGraphFrame min-w-0 h-full min-h-[var(--workflow-graph-height,360px)] w-[var(--workflow-graph-width,720px)] max-w-full overflow-hidden",
  workflowGraphNode:
    "workflowGraphNode min-w-0 absolute left-[var(--workflow-graph-node-x,0px)] top-[var(--workflow-graph-node-y,0px)]",
  workflowGraphNodeDanger:
    "workflowGraphNodeDanger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  workflowGraphNodeNeutral:
    "workflowGraphNodeNeutral min-w-0",
  workflowGraphNodeReady:
    "workflowGraphNodeReady min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  workflowGraphNodeWarning:
    "workflowGraphNodeWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  workflowGraphSvg:
    "workflowGraphSvg min-w-0 absolute inset-0 h-full w-full overflow-visible",
} as const;

export default styles;
